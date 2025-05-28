# coding: utf-8
# 在文件顶部添加新的import
from fabric import Connection
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess

import argparse
import os
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkecs.v2 import *
from huaweicloudsdkeip.v2.region.eip_region import EipRegion
from huaweicloudsdkeip.v2 import *
from huaweicloudsdkcore.exceptions import exceptions
from scheduler.huawei.fabric_login import connect_with_key
console = Console()

# 添加新的SSH配置类
class SSHConfigurator:
    def __init__(self, ak, sk, region):
        self.credentials = BasicCredentials(ak, sk)
        self.region = region

    def generate_ssh_key_locally(self, key_path="~/.ssh/cluster_key"):
        """在本地生成SSH密钥对"""
        expanded_key_path = os.path.expanduser(key_path)
        private_key = expanded_key_path
        public_key = f"{private_key}.pub"

        if os.path.exists(private_key):
            console.print(f"[dim]SSH密钥已存在: {private_key}[/dim]")
            with open(public_key, 'r') as f:
                public_key_content = f.read().strip()
            return private_key, public_key_content

        os.makedirs(os.path.dirname(private_key), exist_ok=True)
        subprocess.run(f'ssh-keygen -t rsa -N "" -f {private_key}', shell=True, check=True)
        os.chmod(private_key, 0o600)
        os.chmod(public_key, 0o644)

        console.print(f"[green]✓ 已生成SSH密钥对: {private_key}[/green]")
        with open(public_key, 'r') as f:
            public_key_content = f.read().strip()
        return private_key, public_key_content

    def clean_and_update_hosts(self, conn, nodes):
        """清理并更新节点的/etc/hosts文件"""
        result = conn.run("cat /etc/hosts", hide=True, warn=True)
        original_lines = result.stdout.splitlines() if result.ok else []
        
        node_hostnames = [node['hostname'] for node in nodes]
        preserved_lines = []
        for line in original_lines:
            if not any(line.strip().endswith(hostname) for hostname in node_hostnames) \
               and not line.strip().startswith('#') \
               and line.strip() != '':
                preserved_lines.append(line)
        
        new_entries = [f"{node['private_ip']}\t{node['hostname']}" for node in nodes]
        new_hosts_content = '\n'.join(preserved_lines + new_entries)
        
        conn.sudo(f"echo '{new_hosts_content}' > /etc/hosts", warn=True)
        console.print(f"[dim]已更新 {conn.host} 的hosts文件[/dim]")

    def configure_node(self, node, initial_key_path, user, nodes, private_key):
        """配置单个节点的SSH免密登录"""
        max_retries = 3
        retry_delay = 10  # 秒
        time.sleep(30)
        print("mydebug:configure node:",node['public_ip'],user,initial_key_path)
        for attempt in range(max_retries):
            try:
                with Connection(
                    host=node['public_ip'],
                    user=user,
                    connect_kwargs={
                        "key_filename": initial_key_path,
                    }
                ) as conn:
                    # Test the connection (optional, but recommended)
                    # 先执行一个简单的命令测试连接是否真正可用
                    conn.run("echo 'Testing SSH connection'", hide=True, warn=True)
                    
                    # 更新hosts文件
                    self.clean_and_update_hosts(conn, nodes)
                    
                    # 配置SSH目录和权限
                    conn.run("mkdir -p ~/.ssh && chmod 700 ~/.ssh", hide=True)
                    
                    # 上传密钥
                    with open(private_key, 'rb') as f:
                        conn.put(f, remote="/tmp/id_rsa_temp")
                    conn.run("mv /tmp/id_rsa_temp ~/.ssh/id_rsa && chmod 600 ~/.ssh/id_rsa", hide=True)
                    
                    with open(f"{private_key}.pub", 'rb') as f:
                        conn.put(f, remote="/tmp/id_rsa_temp.pub")
                    conn.run("mv /tmp/id_rsa_temp.pub ~/.ssh/id_rsa.pub && chmod 644 ~/.ssh/id_rsa.pub", hide=True)
                    
                    # 配置authorized_keys
                    conn.run("cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys", hide=True)
                    
                    # 配置SSH客户端
                    ssh_config = """
    Host *
        StrictHostKeyChecking no
        UserKnownHostsFile /dev/null
        LogLevel ERROR
    """
                    conn.run(f"echo '{ssh_config}' > ~/.ssh/config && chmod 600 ~/.ssh/config", hide=True)
                    
                    console.print(f"[green]✓ 已配置 {node['hostname']} 的SSH免密登录[/green]")
                    return True
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    console.print(f"[yellow]⚠ 配置 {node['hostname']} 失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}[/yellow]")
                    time.sleep(retry_delay)
                    continue
                console.print(f"[red]✗ 配置 {node['hostname']} 失败: {str(e)}[/red]")
                return False
    def configure_cluster_pwdless(self, nodes_info, initial_key_path, user="root"):
        """配置整个集群的免密登录"""
        if not nodes_info:
            console.print("[yellow]⚠ 没有可配置的节点信息[/yellow]")
            return False

        console.rule("[bold blue]配置集群SSH免密登录[/bold blue]")
        
        # 生成密钥对
        private_key, _ = self.generate_ssh_key_locally()
        
        # 准备节点信息
        nodes = [{
            'hostname': f"node-{info['index']}",
            'public_ip': info['public_ip'],
            'private_ip': info['private_ip']
        } for info in nodes_info if info.get('public_ip') != 'N/A']
        
        console.print(f"[cyan]正在为 {len(nodes)} 个节点配置免密登录...[/cyan]")
        
        # 使用线程池并行配置
        success_count = 0
        with ThreadPoolExecutor(max_workers=min(5, len(nodes))) as executor:
            futures = []
            for node in nodes:
                futures.append(executor.submit(
                    self.configure_node, node, initial_key_path, user, nodes, private_key
                ))
            
            for future in as_completed(futures):
                if future.result():
                    success_count += 1
        
        console.print(Panel(
            f"[bold]SSH配置完成![/bold]\n\n"
            f"[white]总节点数:[/white] {len(nodes)}\n"
            f"[green]成功配置:[/green] {success_count}\n"
            f"[red]失败配置:[/red] {len(nodes) - success_count}",
            title="SSH配置结果",
            border_style="blue"
        ))
        
        return success_count == len(nodes)
class EIPManager:
    def __init__(self, ak, sk, region):
        self.credentials = BasicCredentials(ak, sk)
        self.region = EipRegion.value_of(region)
        self.client = EipClient.new_builder() \
            .with_credentials(self.credentials) \
            .with_region(self.region) \
            .build()

    def create_eips(self, num_eips, task_name, bandwidth_size=5):
        """批量创建EIP"""
        created_eips = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            with ThreadPoolExecutor(max_workers=min(num_eips, 10)) as executor:
                futures = {}
                for i in range(num_eips):
                    task_id = progress.add_task(f"EIP {i+1}...", total=100)
                    progress.update(task_id, completed=0)

                    future = executor.submit(
                        self._create_single_eip,
                        progress, task_id,
                        task_name=f"{task_name}_{i+1}",
                        bandwidth_size=bandwidth_size
                    )
                    futures[future] = (i+1, task_id)

                for future in as_completed(futures):
                    eip_index, task_id = futures[future]
                    try:
                        eip_detail = future.result()
                        if eip_detail:
                            created_eips.append(eip_detail)
                        else:
                            progress.update(task_id, description=f"[red]✗ EIP {eip_index} 创建失败", completed=100, visible=False)
                    except Exception as e:
                        progress.update(task_id, description=f"[red]✗ EIP {eip_index} 错误: {e}", completed=100, visible=False)
                        console.print(f"[red]处理EIP {eip_index} 时出错: {e}[/red]")
        
        return created_eips

    def _create_single_eip(self, progress, task_id, task_name, bandwidth_size=5):
        """创建单个EIP"""
        progress.update(task_id, description=f"[cyan]准备创建EIP {task_name}...")
        
        try:
            request = CreatePublicipRequest()
            publicip = CreatePublicipOption(type="5_bgp")
            bandwidth = CreatePublicipBandwidthOption(
                share_type="PER",
                name=task_name,
                size=bandwidth_size
            )
            request.body = CreatePublicipRequestBody(
                bandwidth=bandwidth,
                publicip=publicip,
            )
            
            progress.update(task_id, description=f"[cyan]发送创建请求 {task_name}...")
            response = self.client.create_publicip(request)

            if not response.publicip:
                progress.update(task_id, description=f"[bold red]✗ {task_name} 创建失败: 未返回EIP信息", completed=100, visible=False)
                return None

            pub = response.publicip
            progress.update(task_id, description=f"[green]✓ {task_name} 创建成功 (ID: {pub.id})", completed=100, visible=False)
            
            return {
                'id': pub.id,
                'ip': pub.public_ip_address,
                'name': task_name
            }

        except exceptions.ClientRequestException as e:
            progress.update(task_id, description=f"[bold red]✗ {task_name} 创建异常: {e.error_code}", completed=100, visible=False)
            return None
        except Exception as ex:
            progress.update(task_id, description=f"[bold red]✗ {task_name} 创建未知异常", completed=100, visible=False)
            return None

    def delete_eips(self, eip_ids):
        """批量删除EIP"""
        if not eip_ids:
            console.print("[yellow]⚠ 没有可删除的EIP![/yellow]")
            return True

        success_count = 0
        failed_deletions = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True
        ) as progress_bar:
            with ThreadPoolExecutor(max_workers=min(5, len(eip_ids))) as executor:
                future_to_eip_id = {
                    executor.submit(self._delete_single_eip, progress_bar, eip_id): eip_id
                    for eip_id in eip_ids
                }
                for future in as_completed(future_to_eip_id):
                    eip_id = future_to_eip_id[future]
                    try:
                        if future.result():
                            success_count += 1
                        else:
                            failed_deletions.append(eip_id)
                    except Exception as exc:
                        console.print(f"[red]删除EIP {eip_id} 时发生意外错误: {exc}[/red]")
                        failed_deletions.append(eip_id)

        console.print(Panel(
            f"[bold]EIP删除操作完成![/bold]\n\n"
            f"[white]总尝试删除:[/white] {len(eip_ids)}\n"
            f"[green]成功删除:[/green] {success_count}\n"
            f"[red]删除失败:[/red] {len(failed_deletions)}"
            + (f"\n[white]失败列表:[/white] [red]{', '.join(failed_deletions)}[/red]" if failed_deletions else ""),
            title="EIP删除结果统计",
            border_style="blue"
        ))
        return success_count == len(eip_ids)

    def _delete_single_eip(self, progress, eip_id, max_retries=2):
        """删除单个EIP"""
        task_id = progress.add_task(f"删除EIP {eip_id}...", total=1)
        retry_count = 0
        deleted = False
        
        while retry_count <= max_retries and not deleted:
            progress.update(task_id, description=f"删除EIP {eip_id} (尝试 {retry_count + 1})")
            
            try:
                request = DeletePublicipRequest(publicip_id=eip_id)
                self.client.delete_publicip(request)
                
                progress.update(task_id, description=f"[green]✓ {eip_id} 删除成功!", completed=1)
                deleted = True
                return True
                
            except exceptions.ClientRequestException as e:
                if e.status_code == 404:
                    progress.update(task_id, description=f"[yellow]EIP {eip_id} 不存在或已删除", completed=1)
                    return True
                progress.update(task_id, description=f"[red]删除 {eip_id} 失败: {e.error_code} (尝试 {retry_count + 1})")
                retry_count += 1
                if retry_count <= max_retries: 
                    time.sleep(5 * (retry_count))
            except Exception as ex:
                progress.update(task_id, description=f"[red]删除 {eip_id} 未知错误 (尝试 {retry_count + 1})")
                retry_count += 1
                if retry_count <= max_retries: 
                    time.sleep(5)
        
        if not deleted:
            progress.update(task_id, description=f"[bold red]✗ {eip_id} 删除失败 (最大重试)", completed=1)
        return deleted

class ECSInstanceManager:
    def __init__(self, ak, sk, region):
        self.ak = ak
        self.sk = sk
        self.region = region
        self.credentials = BasicCredentials(ak, sk)
        self.ecs_region = EcsRegion.value_of(region)
        self.client = EcsClient.new_builder() \
            .with_credentials(self.credentials) \
            .with_region(self.ecs_region) \
            .build()
        self.eip_manager = EIPManager(ak, sk, region)
        self.ssh_configurator = SSHConfigurator(ak, sk, region)  # 新增SSH配置器
        self.eip_list = []  # 新增实例变量存储EIP列表

    def create_instance(self, progress, task_id, vpc_id, instance_index, instance_type, instance_zone,
                       ami, key_pair, security_group_id, subnet_id, run_number,
                       task_type, timeout_hours, actor, eip_id=None):
        """创建单个ECS实例"""
        instance_name = f"{run_number}-{task_type}-node{instance_index}-timeout{timeout_hours}-{actor}"
        
        progress.update(task_id, description=f"[cyan]准备创建 {instance_name}...")
        try:
            # 1. 准备创建请求
            request = CreatePostPaidServersRequest()

            # 2. 配置实例参数
            root_volume = PostPaidServerRootVolume(volumetype="SSD")
            nics = [PostPaidServerNic(subnet_id=subnet_id)]
            sg_list = []
            if security_group_id:
                sg_list.append(PostPaidServerSecurityGroup(id=security_group_id))

            user_data_script = f"""#cloud-config
hostname: node{instance_index}-{task_type}"""
            user_data = base64.b64encode(user_data_script.encode('utf-8')).decode('utf-8')

            server_tags = [
                PostPaidServerTag(key="Name", value=f'{run_number}-{task_type}'),
                PostPaidServerTag(key="Index", value=f'{instance_index}'),
                PostPaidServerTag(key="WarningHours", value=timeout_hours),
                PostPaidServerTag(key="Actor", value=actor)
            ]

            terminate_time = datetime.utcnow() + timedelta(hours=int(timeout_hours))
            terminate_time_str = terminate_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            server_body_params = {
                'flavor_ref': instance_type,
                'image_ref': ami,
                'name': instance_name,
                'key_name': key_pair,
                'vpcid': vpc_id,
                'nics': nics,
                'root_volume': root_volume,
                'user_data': user_data,
                'server_tags': server_tags,
                'availability_zone': instance_zone,
                'auto_terminate_time': terminate_time_str
            }
            # 如果需要绑定EIP
            if  eip_id:
                server_body_params['publicip'] = PostPaidServerPublicip(
                    id=eip_id,
                    delete_on_termination=True
                )
            if sg_list:
                server_body_params['security_groups'] = sg_list
            server_body = PostPaidServer(**server_body_params)
            request.body = CreatePostPaidServersRequestBody(server=server_body)

            progress.update(task_id, description=f"[cyan]发送创建请求 {instance_name}...")
            response = self.client.create_post_paid_servers(request)

            if not response.server_ids or len(response.server_ids) == 0:
                progress.update(task_id, description=f"[bold red]✗ {instance_name} 创建失败: 未返回ID", completed=100, visible=False)
                return None

            server_id = response.server_ids[0]
            progress.update(task_id, description=f"[green]✓ {instance_name} 请求成功 (ID: {server_id})...等待就绪")

            instance_details = self._wait_for_instance_ready(progress, task_id, server_id, instance_name)
            if not instance_details:
                progress.update(task_id, description=f"[bold red]✗ {instance_name} 就绪失败", completed=100, visible=False)
                return None
            
            progress.update(task_id, description=f"[bold green]✓ {instance_name} 创建完成!", completed=100, visible=False)
            
            # 修改_create_instance方法中的返回部分
            return {
                'index': instance_index,
                'id': instance_details['id'],
                'name': instance_name,
                'private_ip': instance_details['private_ip'],
                # 如果有EIP，则使用EIP的IP地址，否则使用实例详情中的公网IP或'N/A'
                'public_ip': next((eip['ip'] for eip in self.eip_list if eip['id'] == eip_id), instance_details.get('public_ip', 'N/A')),
                'status': instance_details['status'],
                'eip_id': eip_id
            }

        except exceptions.ClientRequestException as e:
            print(f"创建失败：${e.error_msg}")
            progress.update(task_id, description=f"[bold red]✗ {instance_name} 创建异常: {e.error_code}", completed=100, visible=False)
            return None
        except Exception as ex:
            progress.update(task_id, description=f"[bold red]✗ {instance_name} 创建未知异常", completed=100, visible=False)
            return None

    def _wait_for_instance_ready(self, progress, task_id, server_id, instance_name="[N/A]", timeout=300, interval=10):
        """等待实例变为ACTIVE状态"""
        progress.update(task_id, description=f"[cyan]等待 {instance_name} ({server_id}) 启动...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                detail_request = ShowServerRequest(server_id=server_id)
                detail_response = self.client.show_server(detail_request)
                status = detail_response.server.status
                
                progress.update(task_id, description=f"[cyan]状态 {instance_name}: {status} (等待 {int(time.time()-start_time)}s)")

                if status == "ACTIVE":
                    private_ip = None
                    public_ip = None
                    
                    # 获取私有IP
                    if hasattr(detail_response.server, 'addresses'):
                        for _, ip_list in detail_response.server.addresses.items():
                            for ip_info in ip_list:
                                if ip_info.addr: 
                                    if ip_info.os_ext_ip_stype == 'fixed':
                                        private_ip = ip_info.addr
                                    elif ip_info.os_ext_ip_stype == 'floating':
                                        public_ip = ip_info.addr
                                    break
                            if private_ip and public_ip:
                                break
                    
                    # 获取EIP信息
                    if hasattr(detail_response.server, 'publicip'):
                        public_ip = detail_response.server.publicip.public_ip_address
                    
                    return {
                        'id': detail_response.server.id,
                        'private_ip': private_ip if private_ip else "N/A",
                        'public_ip': public_ip if public_ip else "N/A",
                        'status': status
                    }
                elif status == "ERROR":
                    return None
                time.sleep(interval)
            except exceptions.ClientRequestException as e:
                if e.status_code == 404 or "NotFound" in e.error_code or "Ecs.0114" in e.error_code:
                    progress.update(task_id, description=f"[yellow]{instance_name} 暂未找到, 等待...")
                else:
                    progress.update(task_id, description=f"[red]检查 {instance_name} 状态出错: {e.error_code}")
                time.sleep(interval)
        
        return None

    def delete_instances(self, server_ids, max_retries=2):
        """批量删除ECS实例"""
        if not server_ids:
            console.print("[yellow]⚠ 没有可删除的实例![/yellow]")
            return True

        success_count = 0
        failed_deletions = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True
        ) as progress_bar:
            with ThreadPoolExecutor(max_workers=min(5, len(server_ids))) as executor:
                future_to_server_id = {
                    executor.submit(self._delete_single_instance, progress_bar, server_id, max_retries): server_id
                    for server_id in server_ids
                }
                for future in as_completed(future_to_server_id):
                    server_id = future_to_server_id[future]
                    try:
                        if future.result():
                            success_count += 1
                        else:
                            failed_deletions.append(server_id)
                    except Exception as exc:
                        console.print(f"[red]删除实例 {server_id} 时发生意外错误: {exc}[/red]")
                        failed_deletions.append(server_id)

        console.print(Panel(
            f"[bold]删除操作完成![/bold]\n\n"
            f"[white]总尝试删除:[/white] {len(server_ids)}\n"
            f"[green]成功删除:[/green] {success_count}\n"
            f"[red]删除失败:[/red] {len(failed_deletions)}"
            + (f"\n[white]失败列表:[/white] [red]{', '.join(failed_deletions)}[/red]" if failed_deletions else ""),
            title="删除结果统计",
            border_style="blue"
        ))
        return success_count == len(server_ids)

    def _delete_single_instance(self, progress, server_id, max_retries):
        """Helper method to delete a single instance and handle retries."""
        task_id = progress.add_task(f"删除 {server_id}...", total=1)
        retry_count = 0
        deleted = False
        while retry_count <= max_retries and not deleted:
            progress.update(task_id, description=f"删除 {server_id} (尝试 {retry_count + 1})")
            try:
                request = DeleteServersRequest()
                request.body = DeleteServersRequestBody(
                    servers=[ServerId(id=server_id)],
                    delete_publicip=True,
                    delete_volume=True
                )
                response = self.client.delete_servers(request)
                job_id = response.job_id
                progress.update(task_id, description=f"删除 {server_id}, Job: {job_id}, 等待完成...")

                if self._wait_for_job_complete(progress, task_id, job_id, server_id_for_log=server_id):
                    progress.update(task_id, description=f"[green]✓ {server_id} 删除成功!", completed=1)
                    deleted = True
                    return True
                else:
                    progress.update(task_id, description=f"[yellow]{server_id} Job未成功 (尝试 {retry_count + 1})")
                    retry_count += 1
                    if retry_count <= max_retries: time.sleep(5 * (retry_count))

            except exceptions.ClientRequestException as e:
                progress.update(task_id, description=f"[red]删除 {server_id} 失败: {e.error_code} (尝试 {retry_count + 1})")
                retry_count += 1
                if retry_count <= max_retries: time.sleep(5)
            except Exception as ex:
                progress.update(task_id, description=f"[red]删除 {server_id} 未知错误 (尝试 {retry_count + 1})")
                retry_count += 1
                if retry_count <= max_retries: time.sleep(5)
        
        if not deleted:
            progress.update(task_id, description=f"[bold red]✗ {server_id} 删除失败 (最大重试)", completed=1)
        return deleted

    def _wait_for_job_complete(self, progress, task_id, job_id, server_id_for_log="N/A", max_attempts=30, interval=10):
        """等待作业完成"""
        current_desc_prefix = progress.tasks[task_id].description.split(", 等待完成...")[0] if progress and task_id is not None else f"Job {job_id}"

        for attempt in range(max_attempts):
            progress.update(task_id, description=f"{current_desc_prefix}, Job状态检查 {attempt+1}/{max_attempts}...")
            try:
                job_request = ShowJobRequest(job_id=job_id)
                job_response = self.client.show_job(job_request)
                status = job_response.status
                entity_info = ""
                if hasattr(job_response, 'entities') and job_response.entities and hasattr(job_response.entities, 'server_id'):
                    entity_info = f"(实体ID: {job_response.entities.server_id})"
                elif server_id_for_log != "N/A":
                     entity_info = f"(关联实例: {server_id_for_log})"
                
                progress.update(task_id, description=f"{current_desc_prefix}, Job: {status} {entity_info}")

                if hasattr(job_response, 'sub_jobs') and job_response.sub_jobs:
                    for sub_job in job_response.sub_jobs:
                        if sub_job.status == "FAIL":
                            console.print(f"[yellow]Job {job_id} {entity_info} 的子任务失败 - 类型: {sub_job.type}, 原因: {sub_job.fail_reason}[/yellow]")
                if status == "SUCCESS":
                    return True
                elif status == "FAIL":
                    fail_reason = job_response.fail_reason if hasattr(job_response, 'fail_reason') else "未知原因"
                    console.print(f"[red]Job {job_id} {entity_info} 执行失败! 原因: {fail_reason}[/red]")
                    return False
                time.sleep(interval)
            except exceptions.ClientRequestException as e:
                progress.update(task_id, description=f"{current_desc_prefix}, Job状态检查失败: {e.error_code}")
                time.sleep(interval)
            except Exception as ex_job:
                progress.update(task_id, description=f"{current_desc_prefix}, Job状态意外错误")
                time.sleep(interval)
        
        console.print(f"[yellow]⚠ Job {job_id} {entity_info} 检查超时! 未能在 {max_attempts*interval} 秒内完成[/yellow]")
        return False

    def save_instances_info(self, task_name, instances_info):
        """保存实例信息到文件"""
        os.makedirs("./cache", exist_ok=True)
        filename = f"./cache/{task_name}_instances_info.txt"
        with open(filename, 'w') as f:
            f.write("Index\tID\tName\tPrivateIP\tPublicIP\tStatus\n")
            for info in instances_info:
                f.write(f"{info['index']}\t{info['id']}\t{info['name']}\t{info['private_ip']}\t{info.get('public_ip', 'N/A')}\t{info['status']}\n")
        console.print(f"[dim]实例信息已保存到: [underline]{filename}[/underline][/dim]")
        return filename
def save_eips_to_file(task_name, eip_list):
    """将EIP信息保存到文件"""
    os.makedirs("./cache", exist_ok=True)
    filename = f"./cache/{task_name}_ip_info.txt"
    with open(filename, 'w') as f:
        f.write("ID\tIP\n")  # 表头
        for eip in eip_list:
            if eip:  # 过滤掉创建失败的实例
                f.write(f"{eip['id']}\t{eip['ip']}\n")
    console.print(f"[dim]EIP信息已保存到: [underline]{filename}[/underline][/dim]")

def read_eips_from_file(task_name):
    """从文件读取EIP信息"""
    filename = f"./cache/{task_name}_ip_info.txt"
    if not os.path.exists(filename):
        return None
    
    eip_list = []
    with open(filename, 'r') as f:
        # 跳过表头
        next(f)
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                eip_list.append({
                    'id': parts[0],
                    'ip': parts[1]
                })
    return eip_list

def main():
    parser = argparse.ArgumentParser(
        description='华为云ECS实例创建后自动删除工具 (支持多实例)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python ecs_manager_create_delete.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 \\
    --vpc-id vpc-123 --instance-type kc1.large.4 --key-pair my-key \\
    --security-group-id sg-xxxx --subnet-id subnet-yyyy \\
    --run-number 1002 --task-type test --actor tester --num-instances 3
""")
    parser.add_argument('--ak', required=True, help='华为云Access Key')
    parser.add_argument('--sk', required=True, help='华为云Secret Key')
    parser.add_argument('--region', required=True, help='区域(如: cn-north-4)')
    parser.add_argument('--vpc-id', required=True, help='VPC ID')
    parser.add_argument('--num-instances', type=int, default=1, help='要创建的实例数量')
    parser.add_argument('--instance-type', required=True, help='实例类型 (如: s6.large.2)')
    parser.add_argument('--instance-zone', help='可用区(如: cn-north-4a, 默认: <region>a)', default=None)
    parser.add_argument('--ami', help='镜像ID (如: CentOS 7.x)', default="04b5ea14-da35-47de-8467-66808dd62007")
    parser.add_argument('--key-pair', required=True, help='SSH密钥对名称')
    parser.add_argument('--security-group-id',required=True, help='安全组ID')
    parser.add_argument('--subnet-id',required=True, help='子网ID')
    parser.add_argument('--run-number', required=True, help='运行编号')
    parser.add_argument('--task-type', required=True, help='任务类型')
    parser.add_argument('--timeout-hours', default="1", help='自动终止时间(小时, 默认1小时)')
    parser.add_argument('--actor', required=True, help='操作者')
    parser.add_argument('--use-ip', action='store_true', help='是否分配公网IP (默认为不分配)', default=False)
    parser.add_argument('--bandwidth', type=int, default=5, help='EIP带宽大小(Mbps)')
    args = parser.parse_args()

    manager = ECSInstanceManager(args.ak, args.sk, args.region)
    console.rule(f"[bold blue]测试模式: 创建 {args.num_instances} 个实例后自动删除[/bold blue]")
    instance_zone = args.instance_zone if args.instance_zone else f"{args.region}a"
    created_instances_details = []
    
    if args.use_ip:
        console.print(f"[cyan]正在为 {args.num_instances} 个实例申请EIP...[/cyan]")
        manager.eip_list = manager.eip_manager.create_eips(  # 存储到实例变量
            args.num_instances, 
            f"{args.run_number}_{args.task_type}",
            args.bandwidth
        )
        
        if not manager.eip_list or len(manager.eip_list) < args.num_instances:
            console.print("[red]✗ EIP申请失败或数量不足，无法继续创建实例[/red]")
            return
        save_eips_to_file(f"{args.run_number}_{args.task_type}", manager.eip_list)
        
        # 显示EIP信息
        eip_table = Table(title="已申请EIP列表", show_header=True, header_style="bold cyan")
        eip_table.add_column("序号", style="dim", justify="right")
        eip_table.add_column("EIP ID")
        eip_table.add_column("IP地址")
        for i, eip in enumerate(manager.eip_list, 1):
            eip_table.add_row(str(i), eip['id'], eip['ip'])
        console.print(eip_table)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as creation_progress:
        with ThreadPoolExecutor(max_workers=min(args.num_instances, 10)) as executor:
            futures = {}
            for i in range(args.num_instances):
                task_id = creation_progress.add_task(f"Instance {i}...", total=100, start=False, visible=True)
                creation_progress.update(task_id, completed=0)

                # 如果有EIP列表，获取对应的EIP ID
                eip_id = manager.eip_list[i]['id'] if args.use_ip and i < len(manager.eip_list) else None
                
                future = executor.submit(
                    manager.create_instance,
                    creation_progress, task_id, 
                    vpc_id=args.vpc_id,
                    instance_index=i,
                    instance_type=args.instance_type,
                    instance_zone=instance_zone,
                    ami=args.ami,
                    key_pair=args.key_pair,
                    security_group_id=args.security_group_id,
                    subnet_id=args.subnet_id,
                    run_number=args.run_number,
                    task_type=args.task_type,
                    timeout_hours=args.timeout_hours,
                    actor=args.actor,
                    eip_id=eip_id
                )
                futures[future] = (i, task_id) 

            for future in as_completed(futures):
                instance_index, task_id = futures[future]
                try:
                    instance_detail = future.result()
                    if instance_detail:
                        created_instances_details.append(instance_detail)
                    else:
                        creation_progress.update(task_id, description=f"[red]✗ Instance {instance_index} failed.", completed=100, visible=False)
                except Exception as e:
                    creation_progress.update(task_id, description=f"[red]✗ Instance {instance_index} error: {e}", completed=100, visible=False)
                    console.print(f"[red]Error processing instance {instance_index}: {e}[/red]")

    if not created_instances_details:
        console.print("[red]✗ 测试失败: 没有实例成功创建.[/red]")
        # 清理已申请的EIP
        if args.use_ip and manager.eip_list:
            console.print("[yellow]清理已申请的EIP...[/yellow]")
            manager.eip_manager.delete_eips([eip['id'] for eip in manager.eip_list])
        return

    console.print(f"\n[bold green]总共 {len(created_instances_details)}/{args.num_instances} 个实例创建成功.[/bold green]")
    
    if len(created_instances_details) < args.num_instances:
        console.print(f"[yellow]注意: {args.num_instances - len(created_instances_details)} 个实例创建失败.[/yellow]")

    if created_instances_details:
        # 保存实例信息到文件
        info_file = manager.save_instances_info(
            f"{args.run_number}_{args.task_type}",
            created_instances_details
        )
        # 配置SSH免密登录（仅在成功创建实例且有公网IP时）
        if args.use_ip and any(inst.get('public_ip', 'N/A') != 'N/A' for inst in created_instances_details):
            console.rule("[bold blue]配置SSH免密登录[/bold blue]")
            
            # 获取初始SSH密钥路径（从参数或默认位置）
            # initial_key_path = os.path.expanduser("~/.ssh/id_rsa")  # 默认使用用户的SSH密钥
            # if args.key_pair:
            #     # 如果是华为云的密钥对，可能需要从特定位置获取
            #     initial_key_path = os.path.expanduser(f"~/.ssh/{args.key_pair}.pem")
            initial_key_path="/root/schedule/KeyPair-loacl.pem"
            # 配置免密登录
            ssh_success = manager.ssh_configurator.configure_cluster_pwdless(
                created_instances_details,
                initial_key_path=initial_key_path,
                user="root"
            )
            
            if ssh_success:
                console.print("[bold green]✓ SSH免密登录配置成功![/bold green]")
            else:
                console.print("[yellow]⚠ SSH免密登录配置部分失败[/yellow]")
        
        
        table = Table(title="已创建实例列表 (等待删除)", show_header=True, header_style="bold green")
        table.add_column("序号", style="dim", justify="right")
        table.add_column("名称")
        table.add_column("ID")
        table.add_column("私有IP")
        table.add_column("公网IP")
        table.add_column("状态")
        for inst in sorted(created_instances_details, key=lambda x: x['index']):
            table.add_row(
                str(inst['index']),
                inst['name'],
                inst['id'],
                inst.get('private_ip', 'N/A'),
                inst.get('public_ip', 'N/A'),
                inst['status']
            )
        console.print(table)
        
        server_ids_to_delete = [inst['id'] for inst in created_instances_details]
        eip_ids_to_delete = [inst['eip_id'] for inst in created_instances_details if inst.get('eip_id')]
        
        console.rule("[bold red]自动删除模式[/bold red]")
        wait_seconds = 10
        console.print(f"[yellow]等待 {wait_seconds} 秒后自动删除 {len(server_ids_to_delete)} 个已创建的实例...[/yellow]")
        for i in range(wait_seconds, 0, -1):
            print(f"\r[yellow]开始删除倒计时: {i}s...[/yellow]", end="")
            time.sleep(1)
        print("\r" + " " * 30 + "\r", end="") 

        # 先删除实例
        all_deleted_successfully = manager.delete_instances(server_ids_to_delete)
        
        # 然后删除EIP
        if eip_ids_to_delete:
            console.print("[cyan]开始清理关联的EIP...[/cyan]")
            manager.eip_manager.delete_eips(eip_ids_to_delete)
            
            # 清理文件
            info_path = f"./cache/{args.run_number}_{args.task_type}_ip_info.txt"
            if os.path.exists(info_path):
                os.remove(info_path)
                console.print(f"[dim]已清理文件: {info_path}[/dim]")

        if all_deleted_successfully:
            if len(server_ids_to_delete) == args.num_instances :
                 console.print(f"[bold green]✓ 测试完成: {len(server_ids_to_delete)} 个实例全部创建并成功删除![/bold green]")
            else:
                 console.print(f"[bold green]✓ 测试部分完成: {len(server_ids_to_delete)}/{args.num_instances} 个实例创建并成功删除! (其余实例创建失败)[/bold green]")
        else:
            console.print(f"[bold red]✗ 测试失败: 部分或全部实例 (共 {len(server_ids_to_delete)} 个尝试删除) 删除失败.[/bold red]")
    else:
        console.print("[red]⚠ 没有实例创建成功，因此不执行删除操作.[/red]")

if __name__ == "__main__":
    main()