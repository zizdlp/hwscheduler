# coding: utf-8
import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkeip.v2.region.eip_region import EipRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkeip.v2 import *

console = Console()

class EIPManager:
    def __init__(self, ak, sk, region):
        self.credentials = BasicCredentials(ak, sk)
        self.region = EipRegion.value_of(region)
        self.client = EipClient.new_builder() \
            .with_credentials(self.credentials) \
            .with_region(self.region) \
            .build()

    def create_eip(self, progress, task_id, task_name, bandwidth_size=5):
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
                console.print(Panel(
                    f"[bold red]✗ EIP {task_name} 创建失败![/bold red]\n\n"
                    f"[white]原因:[/white] 未返回EIP信息",
                    border_style="red"
                ))
                return None

            pub = response.publicip
            progress.update(task_id, description=f"[green]✓ {task_name} 创建成功 (ID: {pub.id})", completed=100, visible=False)
            
            console.print(Panel(
                f"[bold green]✓ EIP创建成功![/bold green]\n\n"
                f"[white]名称:[/white] [cyan]{task_name}[/cyan]\n"
                f"[white]ID:[/white] [yellow]{pub.id}[/yellow]\n"
                f"[white]IP地址:[/white] [blue]{pub.public_ip_address}[/blue]",
                title=f"创建结果: {task_name}",
                border_style="green"
            ))

            return {
                'id': pub.id,
                'ip': pub.public_ip_address,
                'name': task_name
            }

        except exceptions.ClientRequestException as e:
            progress.update(task_id, description=f"[bold red]✗ {task_name} 创建异常: {e.error_code}", completed=100, visible=False)
            console.print(Panel(
                f"[bold red]✗ EIP {task_name} 创建失败![/bold red]\n\n"
                f"[white]错误代码:[/white] {e.error_code}\n"
                f"[white]错误信息:[/white] {e.error_msg}",
                border_style="red"
            ))
            return None
        except Exception as ex:
            progress.update(task_id, description=f"[bold red]✗ {task_name} 创建未知异常", completed=100, visible=False)
            console.print(Panel(
                f"[bold red]✗ EIP {task_name} 创建时发生意外错误![/bold red]\n\n"
                f"[white]错误:[/white] {str(ex)}",
                border_style="red"
            ))
            return None

    def delete_eip(self, progress, task_id, eip_id, max_retries=2):
        """删除单个EIP"""
        retry_count = 0
        deleted = False
        
        while retry_count <= max_retries and not deleted:
            progress.update(task_id, description=f"删除 {eip_id} (尝试 {retry_count + 1})")
            
            try:
                request = DeletePublicipRequest(publicip_id=eip_id)
                response = self.client.delete_publicip(request)
                
                progress.update(task_id, description=f"[green]✓ {eip_id} 删除成功!", completed=100, visible=False)
                console.print(f"[green]✓ EIP {eip_id} 删除成功![/green]")
                deleted = True
                return True
                
            except exceptions.ClientRequestException as e:
                progress.update(task_id, description=f"[red]删除 {eip_id} 失败: {e.error_code} (尝试 {retry_count + 1})")
                console.print(f"[red]删除EIP {eip_id} 失败: {e.error_msg} (尝试 {retry_count + 1}/{max_retries + 1})[/red]")
                retry_count += 1
                if retry_count <= max_retries: 
                    time.sleep(5 * (retry_count))
            except Exception as ex:
                progress.update(task_id, description=f"[red]删除 {eip_id} 未知错误 (尝试 {retry_count + 1})")
                console.print(f"[bold red]✗ 删除EIP {eip_id} 时发生未知错误: {str(ex)} (尝试 {retry_count + 1}/{max_retries + 1})[/bold red]")
                retry_count += 1
                if retry_count <= max_retries: 
                    time.sleep(5)
        
        if not deleted:
            progress.update(task_id, description=f"[bold red]✗ {eip_id} 删除失败 (最大重试)", completed=100, visible=False)
            console.print(f"[bold red]✗ EIP {eip_id} 删除失败，已达最大重试次数.[/bold red]")
        return deleted

    def delete_eips(self, eip_list, max_retries=2):
        """批量删除EIP"""
        if not eip_list:
            console.print("[yellow]⚠ 没有可删除的EIP![/yellow]")
            return True

        table = Table(title="待删除EIP列表", show_header=True, header_style="bold magenta")
        table.add_column("序号", style="dim", justify="right")
        table.add_column("EIP ID")
        for i, eip_id in enumerate(eip_list, 1):
            table.add_row(str(i), eip_id)
        console.print(table)
        console.print("[bold]开始删除EIP...[/bold]")

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
            with ThreadPoolExecutor(max_workers=min(5, len(eip_list))) as executor:
                future_to_eip_id = {
                    executor.submit(self.delete_eip, progress_bar, progress_bar.add_task(f"删除 {eip_id}..."), eip_id, max_retries): eip_id
                    for eip_id in eip_list
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
            f"[bold]删除操作完成![/bold]\n\n"
            f"[white]总尝试删除:[/white] {len(eip_list)}\n"
            f"[green]成功删除:[/green] {success_count}\n"
            f"[red]删除失败:[/red] {len(failed_deletions)}"
            + (f"\n[white]失败列表:[/white] [red]{', '.join(failed_deletions)}[/red]" if failed_deletions else ""),
            title="删除结果统计",
            border_style="blue"
        ))
        return success_count == len(eip_list)

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

def main():
    parser = argparse.ArgumentParser(
        description='华为云EIP生命周期管理 (支持多实例并行操作)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 创建指定数量的EIP并自动删除:
  python eip_manager.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 --task mytask --num 3 --auto-clean

  # 仅创建指定数量的EIP:
  python eip_manager.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 --task mytask --num 2

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
    parser.add_argument('--num', type=int, default=1, help='创建/删除的EIP数量')
    parser.add_argument('--bandwidth', type=int, default=5, help='EIP带宽大小(Mbps)')

    args = parser.parse_args()

    manager = EIPManager(args.ak, args.sk, args.region)

    if args.task:
        # 创建EIP流程
        console.rule(f"[bold blue]创建 {args.num} 个EIP[/bold blue]")
        created_eips = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as creation_progress:
            with ThreadPoolExecutor(max_workers=min(args.num, 10)) as executor:
                futures = {}
                for i in range(args.num):
                    task_id = creation_progress.add_task(f"EIP {i+1}...", total=100)
                    creation_progress.update(task_id, completed=0)

                    future = executor.submit(
                        manager.create_eip,
                        creation_progress, task_id,
                        task_name=f"{args.task}_{i+1}",
                        bandwidth_size=args.bandwidth
                    )
                    futures[future] = (i+1, task_id)

                for future in as_completed(futures):
                    instance_index, task_id = futures[future]
                    try:
                        eip_detail = future.result()
                        if eip_detail:
                            created_eips.append(eip_detail)
                        else:
                            creation_progress.update(task_id, description=f"[red]✗ EIP {instance_index} 创建失败", completed=100, visible=False)
                    except Exception as e:
                        creation_progress.update(task_id, description=f"[red]✗ EIP {instance_index} 错误: {e}", completed=100, visible=False)
                        console.print(f"[red]处理EIP {instance_index} 时出错: {e}[/red]")

        if not created_eips:
            console.print("[red]✗ 操作失败: 没有EIP成功创建.[/red]")
            return

        console.print(f"\n[bold green]总共 {len(created_eips)}/{args.num} 个EIP创建成功.[/bold green]")
        
        if len(created_eips) < args.num:
            console.print(f"[yellow]注意: {args.num - len(created_eips)} 个EIP创建失败.[/yellow]")

        # 保存到文件
        save_eips_to_file(args.task, created_eips)

        if args.auto_clean and created_eips:
            console.rule("[bold red]自动清理模式[/bold red]", style="red")
            console.print(f"[yellow]等待3秒后自动删除 {len(created_eips)} 个已创建的EIP...[/yellow]")
            time.sleep(3)

            # 自动删除刚创建的EIP
            eip_ids_to_delete = [eip['id'] for eip in created_eips]
            all_deleted = manager.delete_eips(eip_ids_to_delete)

            # 清理文件
            info_path = f"./cache/{args.task}_ip_info.txt"
            if os.path.exists(info_path):
                os.remove(info_path)
                console.print(f"[dim]已清理文件: {info_path}[/dim]")

    elif args.ip_id:
        # 删除单个EIP
        console.rule(f"[bold red]删除单个EIP[/bold red]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True
        ) as progress:
            task_id = progress.add_task(f"删除 {args.ip_id}...", total=1)
            manager.delete_eip(progress, task_id, args.ip_id)

    elif args.info_path:
        # 从文件批量删除
        console.rule(f"[bold red]从文件批量删除EIP[/bold red]")
        if not os.path.exists(args.info_path):
            console.print(Panel(
                f"[bold red]✗ 文件不存在![/bold red]\n\n"
                f"[white]路径:[/white] {args.info_path}",
                border_style="red"
            ))
            return

        try:
            with open(args.info_path, 'r') as f:
                lines = f.readlines()
                eip_list = []
                
                # 跳过表头
                if lines and lines[0].strip().lower() in ['id,ip', 'id\tip']:
                    lines = lines[1:]

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    if '\t' in line:
                        eip_id = line.split('\t')[0]
                    elif ',' in line:
                        eip_id = line.split(',')[0]
                    else:
                        eip_id = line

                    eip_list.append(eip_id.strip())

            if not eip_list:
                console.print("[yellow]! 文件中没有有效的EIP信息[/yellow]")
                return

            # 确认删除
            if not console.input("[bold]确认删除以上EIP吗? (y/n): [/bold]").lower() == 'y':
                console.print("[yellow]操作已取消[/yellow]")
                return

            manager.delete_eips(eip_list)

        except Exception as e:
            console.print(Panel(
                f"[bold red]✗ 处理文件出错![/bold red]\n\n"
                f"[white]错误信息:[/white] {str(e)}",
                border_style="red"
            ))

    else:
        parser.print_help()

if __name__ == "__main__":
    main()