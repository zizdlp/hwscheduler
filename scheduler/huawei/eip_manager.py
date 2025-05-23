# coding: utf-8
import argparse
import os
import time
from rich.console import Console
from rich.progress import Progress
from rich.panel import Panel
from rich.table import Table
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkeip.v2.region.eip_region import EipRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkeip.v2 import *

console = Console()

def create_eip(ak, sk, region, task_name):
    """创建弹性公网IP"""
    with console.status("[bold cyan]正在创建EIP..."):
        credentials = BasicCredentials(ak, sk)
        eip_region = EipRegion.value_of(region)
        client = EipClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(eip_region) \
            .build()

        try:
            request = CreatePublicipRequest()
            publicip = CreatePublicipOption(type="5_bgp")
            bandwidth = CreatePublicipBandwidthOption(
                share_type="PER", 
                name=task_name, 
                size=5
            )
            request.body = CreatePublicipRequestBody(
                bandwidth=bandwidth,
                publicip=publicip,
            )
            response = client.create_publicip(request)

            if response.publicip:
                pub = response.publicip
                console.print(Panel(
                    f"[bold green]✓ EIP创建成功!\n\n"
                    f"[white]ID:[/white] [cyan]{pub.id}[/cyan]\n"
                    f"[white]IP地址:[/white] [yellow]{pub.public_ip_address}[/yellow]",
                    title="创建结果",
                    border_style="green"
                ))
                
                # 写入文件
                os.makedirs("./cache", exist_ok=True)
                filename = f"./cache/{task_name}_ip_info.txt"
                with open(filename, 'w') as f:
                    f.write(f"{pub.id}\t{pub.public_ip_address}\n")
                
                console.print(f"[dim]EIP信息已保存到: [underline]{filename}[/underline][/dim]")
                return pub

        except exceptions.ClientRequestException as e:
            console.print(Panel(
                f"[bold red]✗ 创建失败![/bold red]\n\n"
                f"[white]错误代码:[/white] {e.error_code}\n"
                f"[white]错误信息:[/white] {e.error_msg}",
                border_style="red"
            ))
            return None

def delete_eip(ak, sk, region, publicip_id):
    """删除单个EIP"""
    with console.status(f"[bold yellow]正在删除EIP {publicip_id}..."):
        credentials = BasicCredentials(ak, sk)
        eip_region = EipRegion.value_of(region)
        client = EipClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(eip_region) \
            .build()

        try:
            request = DeletePublicipRequest(publicip_id=publicip_id)
            response = client.delete_publicip(request)
            console.print(f"[green]✓ 成功删除EIP: [bold]{publicip_id}[/bold][/green]")
            return True

        except exceptions.ClientRequestException as e:
            console.print(Panel(
                f"[bold red]✗ 删除失败![/bold red]\n\n"
                f"[white]EIP ID:[/white] {publicip_id}\n"
                f"[white]错误代码:[/white] {e.error_code}\n"
                f"[white]错误信息:[/white] {e.error_msg}",
                border_style="red"
            ))
            return False

def delete_eip_bytask(ak, sk, region, info_path):
    """从文件批量删除EIP"""
    if not os.path.exists(info_path):
        console.print(Panel(
            f"[bold red]✗ 文件不存在![/bold red]\n\n"
            f"[white]路径:[/white] {info_path}",
            border_style="red"
        ))
        return False

    try:
        with open(info_path, 'r') as f:
            lines = f.readlines()
            
            # 跳过表头
            if lines[0].strip().lower() in ['id,ip', 'id\tip']:
                lines = lines[1:]
                
            eip_list = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                if '\t' in line:
                    eip_id, eip_address = line.split('\t')[:2]
                elif ',' in line:
                    eip_id, eip_address = line.split(',')[:2]
                else:
                    eip_id = line
                    
                eip_list.append(eip_id.strip())

        if not eip_list:
            console.print("[yellow]! 文件中没有有效的EIP信息[/yellow]")
            return False

        # 显示删除摘要
        table = Table(title="待删除EIP列表", show_header=True, header_style="bold magenta")
        table.add_column("序号", style="dim")
        table.add_column("EIP ID")
        for i, eip_id in enumerate(eip_list, 1):
            table.add_row(str(i), eip_id)
        console.print(table)

        # 确认删除
        if not console.input("[bold]确认删除以上EIP吗? (y/n): [/bold]").lower() == 'y':
            console.print("[yellow]操作已取消[/yellow]")
            return False

        # 执行删除
        success_count = 0
        with Progress() as progress:
            task = progress.add_task("[cyan]删除进度...", total=len(eip_list))
            for eip_id in eip_list:
                if delete_eip(ak, sk, region, eip_id):
                    success_count += 1
                progress.update(task, advance=1)

        console.print(Panel(
            f"[bold]删除完成![/bold]\n\n"
            f"[white]总数:[/white] {len(eip_list)}\n"
            f"[green]成功:[/green] {success_count}\n"
            f"[red]失败:[/red] {len(eip_list)-success_count}",
            title="结果统计",
            border_style="blue"
        ))
        return True
        
    except Exception as e:
        console.print(Panel(
            f"[bold red]✗ 处理文件出错![/bold red]\n\n"
            f"[white]错误信息:[/white] {str(e)}",
            border_style="red"
        ))
        return False

if __name__ == "__main__":
    # 初始化命令行参数
    parser = argparse.ArgumentParser(
        description='华为云EIP生命周期管理',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 创建EIP并自动删除:
  python eip_manager.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 --task mytask --auto-clean

  # 仅创建EIP:
  python eip_manager.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 --task mytask

  # 删除特定EIP:
  python eip_manager.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 --ip-id xxxxx

  # 从文件批量删除:
  python eip_manager.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 --info-path ./cache/mytask_ip_info.txt
""")
    parser.add_argument('--ak', required=True, help='华为云Access Key')
    parser.add_argument('--sk', required=True, help='华为云Secret Key')
    parser.add_argument('--region', required=True, help='区域(如: cn-east-3)')
    parser.add_argument('--task', help='任务名称(用于创建EIP)')
    parser.add_argument('--ip-id', help='要删除的EIP ID')
    parser.add_argument('--info-path', help='包含EIP信息的文件路径')
    parser.add_argument('--auto-clean', action='store_true', 
                      help='创建后自动删除(需配合--task使用)')
    
    args = parser.parse_args()

    # 主流程控制
    if args.task:
        # 创建EIP流程
        created_eip = create_eip(args.ak, args.sk, args.region, args.task)
        
        if created_eip and args.auto_clean:
            console.rule("[bold]自动清理模式[/bold]", style="red")
            time.sleep(3)  # 等待时间，让用户可以看到创建结果
            
            # 自动删除刚创建的EIP
            info_path = f"./cache/{args.task}_ip_info.txt"
            console.print(f"[bold]准备删除刚创建的EIP: [cyan]{created_eip.id}[/cyan][/bold]")
            delete_eip(args.ak, args.sk, args.region, created_eip.id)
            
            # 清理文件
            if os.path.exists(info_path):
                os.remove(info_path)
                console.print(f"[dim]已清理文件: {info_path}[/dim]")
    
    elif args.ip_id:
        # 删除单个EIP
        delete_eip(args.ak, args.sk, args.region, args.ip_id)
    
    elif args.info_path:
        # 从文件批量删除
        delete_eip_bytask(args.ak, args.sk, args.region, args.info_path)
    
    else:
        parser.print_help()