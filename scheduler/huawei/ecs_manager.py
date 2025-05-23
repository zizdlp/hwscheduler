# coding: utf-8
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
# from rich.style import Style # Style is not used directly, can be removed if not planned
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkecs.v2 import *
from huaweicloudsdkcore.exceptions import exceptions

console = Console()

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

    def create_instance(self, progress, task_id, vpc_id, instance_index, instance_type, instance_zone,
                       ami, key_pair, security_group_id, subnet_id, run_number,
                       task_type, timeout_hours, actor, use_ip=True):
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
            if sg_list:
                server_body_params['security_groups'] = sg_list
            server_body = PostPaidServer(**server_body_params)
            request.body = CreatePostPaidServersRequestBody(server=server_body)

            progress.update(task_id, description=f"[cyan]发送创建请求 {instance_name}...")
            response = self.client.create_post_paid_servers(request)

            if not response.server_ids or len(response.server_ids) == 0:
                progress.update(task_id, description=f"[bold red]✗ {instance_name} 创建失败: 未返回ID", completed=100, visible=False)
                console.print(Panel(
                    f"[bold red]✗ 实例 {instance_name} 创建失败![/bold red]\n\n"
                    f"[white]原因:[/white] 未返回服务器ID",
                    border_style="red"
                ))
                return None

            server_id = response.server_ids[0]
            progress.update(task_id, description=f"[green]✓ {instance_name} 请求成功 (ID: {server_id})...等待就绪")
            # console.print(f"[green]✓ 实例 {instance_name} 创建请求提交成功![/green] [dim]服务器ID: {server_id}[/dim]")

            instance_details = self._wait_for_instance_ready(progress, task_id, server_id, instance_name)
            if not instance_details:
                progress.update(task_id, description=f"[bold red]✗ {instance_name} 就绪失败", completed=100, visible=False)
                return None
            
            progress.update(task_id, description=f"[bold green]✓ {instance_name} 创建完成!", completed=100, visible=False)
            console.print(Panel(
                f"[bold green]✓ 实例创建完成![/bold green]\n\n"
                f"[white]名称:[/white] [cyan]{instance_name}[/cyan]\n"
                f"[white]ID:[/white] [yellow]{instance_details['id']}[/yellow]\n"
                f"[white]私有IP:[/white] [blue]{instance_details['private_ip']}[/blue]\n"
                f"[white]状态:[/white] [green]{instance_details['status']}[/green]",
                title=f"创建结果: {instance_name}",
                border_style="green"
            ))

            return {
                'index': instance_index,
                'id': instance_details['id'],
                'name': instance_name,
                'private_ip': instance_details['private_ip'],
                'status': instance_details['status']
            }

        except exceptions.ClientRequestException as e:
            progress.update(task_id, description=f"[bold red]✗ {instance_name} 创建异常: {e.error_code}", completed=100, visible=False)
            console.print(Panel(
                f"[bold red]✗ 实例 {instance_name} 创建失败![/bold red]\n\n"
                f"[white]错误代码:[/white] {e.error_code}\n"
                f"[white]错误信息:[/white] {e.error_msg}",
                border_style="red"
            ))
            return None
        except Exception as ex:
            progress.update(task_id, description=f"[bold red]✗ {instance_name} 创建未知异常", completed=100, visible=False)
            console.print(Panel(
                f"[bold red]✗ 实例 {instance_name} 创建时发生意外错误![/bold red]\n\n"
                f"[white]错误:[/white] {str(ex)}",
                border_style="red"
            ))
            return None


    def _wait_for_instance_ready(self, progress, task_id, server_id, instance_name="[N/A]", timeout=300, interval=10):
        """等待实例变为ACTIVE状态"""
        # console.print(f"[dim]等待实例 {instance_name} ({server_id}) 启动 (超时: {timeout}秒)...[/dim]")
        progress.update(task_id, description=f"[cyan]等待 {instance_name} ({server_id}) 启动...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                detail_request = ShowServerRequest(server_id=server_id)
                detail_response = self.client.show_server(detail_request)
                status = detail_response.server.status
                
                progress.update(task_id, description=f"[cyan]状态 {instance_name}: {status} (等待 {int(time.time()-start_time)}s)")
                # console.print(f"[dim]实例 {instance_name} 当前状态: {status} (已等待 {int(time.time()-start_time)}秒)[/dim]")

                if status == "ACTIVE":
                    private_ip = None
                    if hasattr(detail_response.server, 'addresses'):
                        for _, ip_list in detail_response.server.addresses.items():
                            for ip_info in ip_list:
                                if ip_info.addr: 
                                    private_ip = ip_info.addr
                                    break
                            if private_ip:
                                break
                    if not private_ip and hasattr(detail_response.server, 'metadata') and 'private_ip' in detail_response.server.metadata:
                         private_ip = detail_response.server.metadata['private_ip']
                    return {
                        'id': detail_response.server.id,
                        'private_ip': private_ip if private_ip else "N/A",
                        'status': status
                    }
                elif status == "ERROR":
                    # progress.update(task_id, description=f"[bold red]✗ {instance_name} ({server_id}) 状态 ERROR") # Handled by caller
                    console.print(f"[bold red]✗ 实例 {instance_name} ({server_id}) 创建失败! 状态: ERROR[/bold red]")
                    return None
                time.sleep(interval)
            except exceptions.ClientRequestException as e:
                if e.status_code == 404 or "NotFound" in e.error_code or "Ecs.0114" in e.error_code:
                    progress.update(task_id, description=f"[yellow]{instance_name} 暂未找到, 等待...")
                    # console.print(f"[yellow]实例 {instance_name} ({server_id}) 暂未找到，继续等待... (错误: {e.error_code})[/yellow]")
                else:
                    progress.update(task_id, description=f"[red]检查 {instance_name} 状态出错: {e.error_code}")
                    # console.print(f"[red]检查实例 {instance_name} ({server_id}) 状态时出错: {e.error_msg}[/red]")
                time.sleep(interval)
        
        # progress.update(task_id, description=f"[yellow]⚠ {instance_name} 等待超时") # Handled by caller
        console.print(f"[yellow]⚠ 等待超时! 实例 {instance_name} ({server_id}) 未在 {timeout} 秒内变为ACTIVE状态[/yellow]")
        return None

    def delete_instances(self, server_ids, max_retries=2):
        """批量删除ECS实例"""
        if not server_ids:
            console.print("[yellow]⚠ 没有可删除的实例![/yellow]")
            return True

        table = Table(title="待删除实例列表", show_header=True, header_style="bold magenta")
        table.add_column("序号", style="dim", justify="right")
        table.add_column("实例ID")
        for i, server_id in enumerate(server_ids, 1):
            table.add_row(str(i), server_id)
        console.print(table)
        console.print("[bold]开始删除实例...[/bold]")

        success_count = 0
        failed_deletions = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True # Makes progress disappear on completion
        ) as progress_bar:
            # delete_overall_task = progress_bar.add_task("[red]删除实例...", total=len(server_ids)) # Use this if not using ThreadPool
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
                    # progress_bar.update(delete_overall_task, advance=1) # Use this if not using ThreadPool

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
                # console.print(f"[dim]实例 {server_id} 删除操作已提交，Job ID: {job_id}[/dim]")

                if self._wait_for_job_complete(progress, task_id, job_id, server_id_for_log=server_id):
                    progress.update(task_id, description=f"[green]✓ {server_id} 删除成功!", completed=1)
                    # console.print(f"[green]✓ 实例 {server_id} 删除成功![/green]")
                    deleted = True
                    return True
                else:
                    progress.update(task_id, description=f"[yellow]{server_id} Job未成功 (尝试 {retry_count + 1})")
                    # console.print(f"[yellow]实例 {server_id} 删除Job未成功完成 (尝试 {retry_count + 1}/{max_retries + 1})[/yellow]")
                    retry_count += 1
                    if retry_count <= max_retries: time.sleep(5 * (retry_count))

            except exceptions.ClientRequestException as e:
                progress.update(task_id, description=f"[red]删除 {server_id} 失败: {e.error_code} (尝试 {retry_count + 1})")
                # console.print(f"[red]删除实例 {server_id} 失败: {e.error_msg} (尝试 {retry_count + 1}/{max_retries + 1})[/red]")
                retry_count += 1
                if retry_count <= max_retries: time.sleep(5)
            except Exception as ex:
                progress.update(task_id, description=f"[red]删除 {server_id} 未知错误 (尝试 {retry_count + 1})")
                # console.print(f"[bold red]✗ 删除实例 {server_id} 时发生未知错误: {str(ex)} (尝试 {retry_count + 1}/{max_retries + 1})[/bold red]")
                retry_count += 1
                if retry_count <= max_retries: time.sleep(5)
        
        if not deleted:
            progress.update(task_id, description=f"[bold red]✗ {server_id} 删除失败 (最大重试)", completed=1)
            # console.print(f"[bold red]✗ 实例 {server_id} 删除失败，已达最大重试次数.[/bold red]")
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
                # console.print(f"[dim]Job {job_id} {entity_info} 状态检查 [{attempt+1}/{max_attempts}]: {status}[/dim]")

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
                # console.print(f"[red]检查Job {job_id} {entity_info} 状态失败: {e.error_code} - {e.error_msg}[/red]")
                time.sleep(interval)
            except Exception as ex_job:
                progress.update(task_id, description=f"{current_desc_prefix}, Job状态意外错误")
                # console.print(f"[red]检查Job {job_id} {entity_info} 状态时发生意外错误: {str(ex_job)}[/red]")
                time.sleep(interval)
        
        console.print(f"[yellow]⚠ Job {job_id} {entity_info} 检查超时! 未能在 {max_attempts*interval} 秒内完成[/yellow]")
        return False
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
    args = parser.parse_args()

    manager = ECSInstanceManager(args.ak, args.sk, args.region)
    console.rule(f"[bold blue]测试模式: 创建 {args.num_instances} 个实例后自动删除[/bold blue]")
    instance_zone = args.instance_zone if args.instance_zone else f"{args.region}a"
    created_instances_details = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        # transient=True # Keep it visible until all creation tasks are done or explicitly hidden
    ) as creation_progress:
        with ThreadPoolExecutor(max_workers=min(args.num_instances, 10)) as executor:
            futures = {}
            for i in range(args.num_instances):
                task_id = creation_progress.add_task(f"Instance {i}...", total=100, start=False, visible=True) # total=100 for percentage
                creation_progress.update(task_id, completed=0)

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
                    use_ip=args.use_ip
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
        return

    # Corrected line below:
    console.print(f"\n[bold green]总共 {len(created_instances_details)}/{args.num_instances} 个实例创建成功.[/bold green]")
    
    if len(created_instances_details) < args.num_instances:
        console.print(f"[yellow]注意: {args.num_instances - len(created_instances_details)} 个实例创建失败.[/yellow]")

    if created_instances_details:
        table = Table(title="已创建实例列表 (等待删除)", show_header=True, header_style="bold green")
        table.add_column("序号", style="dim", justify="right")
        table.add_column("名称")
        table.add_column("ID")
        table.add_column("私有IP")
        table.add_column("状态")
        for inst in sorted(created_instances_details, key=lambda x: x['index']):
            table.add_row(
                str(inst['index']),
                inst['name'],
                inst['id'],
                inst.get('private_ip', 'N/A'),
                inst['status']
            )
        console.print(table)
        server_ids_to_delete = [inst['id'] for inst in created_instances_details]
        console.rule("[bold red]自动删除模式[/bold red]")
        wait_seconds = 10 
        console.print(f"[yellow]等待 {wait_seconds} 秒后自动删除 {len(server_ids_to_delete)} 个已创建的实例...[/yellow]")
        for i in range(wait_seconds, 0, -1):
            print(f"\r[yellow]开始删除倒计时: {i}s...[/yellow]", end="")
            time.sleep(1)
        print("\r" + " " * 30 + "\r", end="") 

        all_deleted_successfully = manager.delete_instances(server_ids_to_delete)
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