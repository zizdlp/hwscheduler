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
from hwscheduler.huawei.fabric_login import connect_with_key
from hwscheduler.huawei.ecs_manager import ECSInstanceManager,save_eips_to_file
from hwscheduler.huawei.test_build_chukonu import test_build_chukonu
console = Console()

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
        test_build_chukonu(created_instances_details[0]['public_ip'],initial_key_path,"root")
        
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