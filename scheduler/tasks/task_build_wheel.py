# coding: utf-8
from fabric import Connection
from concurrent.futures import ThreadPoolExecutor
import os
import argparse
import time
from concurrent.futures import as_completed
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from huaweicloudsdkecs.v2 import *
from huaweicloudsdkeip.v2 import *
from scheduler.huawei.ecs_manager import ECSInstanceManager, save_eips_to_file

console = Console()

def print_step_header(title: str, style: str = "bold blue"):
    """打印步骤标题"""
    console.rule(f"[{style}]{title}[/{style}]")

def print_success(message: str):
    """打印成功信息"""
    console.print(f"[bold green]✓ {message}[/bold green]")

def print_warning(message: str):
    """打印警告信息"""
    console.print(f"[bold yellow]⚠ {message}[/bold yellow]")

def print_error(message: str):
    """打印错误信息"""
    console.print(f"[bold red]✗ {message}[/bold red]")

def print_info(message: str):
    """打印信息"""
    console.print(f"[cyan]ℹ {message}[/cyan]")

def step_build_wheel(node: str, initial_key_path: str, user: str, task_name: str) -> bool:
    """
    Build and install Chukonu on the specified node and collect test results
    """
    conn = None
    test_logs_dir = ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    success = False
    
    try:
        print_step_header(f"Building wheel on {node}")
        
        conn = Connection(
            host=node,
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
        )
        conn.open()
        
        # Set environment variables
        conn.config.run.env = {
            'JAVA_HOME': '/usr/lib/jvm/java-11-openjdk-arm64',
            'CHUKONU_HOME': '/root/chukonu/install',
            'LD_LIBRARY_PATH': '/root/chukonu/install/lib:/tmp/cache',
            'CHUKONU_TEMP': '/tmp',
            'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        }
        
        # Create necessary directories
        conn.run("mkdir -p /tmp/staging /tmp/cache /root/chukonu/build /root/chukonu/install")
        
        # Create timestamped test logs directory
        test_logs_dir = f"/tmp/chukonu_spark_test_logs_{timestamp}"
        conn.run(f"mkdir -p {test_logs_dir}")
        conn.put("./utils/build_wheel.sh", "/root/build_wheel.sh")

        commands = [
            ("docker start manylinux && docker exec manylinux /bin/bash -c 'bash /io/build_wheel.sh'", 
             'build_wheel.log'),
        ]
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("[cyan]Building wheel...", total=len(commands))
            
            for cmd, logfile in commands:
                progress.update(task, description=f"[cyan]Running: {cmd[:50]}...")
                log_path = f"{test_logs_dir}/{logfile}"
                result = conn.run(f"{cmd} > {log_path} 2>&1", warn=True)
                
                if not result.ok:
                    print_error(f"Command failed on {node}: {cmd}")
                    print_info(f"Check log file at {log_path}")
                    success = False
                    break
                
                progress.update(task, advance=1)
        
        if success:
            conn.run(f"cp /root/chukonu/python/wheelhouse/chukonu-1.1.0-py3-none-manylinux2014_aarch64.manylinux_2_17_aarch64.whl {test_logs_dir}/chukonu-1.1.0-py3-none-manylinux2014_aarch64.manylinux_2_17_aarch64.whl")
            print_success(f"Wheel built successfully on {node}")
        
    except Exception as e:
        print_error(f"Exception occurred during build on {node}: {str(e)}")
        success = False
    finally:
        try:
            if conn is not None and conn.is_connected:
                if test_logs_dir:
                    print_info("Compressing test logs...")
                    conn.run(f"tar -czf {test_logs_dir}.tar.gz -C {test_logs_dir} .")
                    
                    local_cache_dir = "./logs"
                    local_log_path = os.path.join(local_cache_dir, f"chukonu_logs_{task_name}_{timestamp}.tar.gz")
                    os.makedirs(local_cache_dir, exist_ok=True)
                    conn.get(f"{test_logs_dir}.tar.gz", local_log_path)
                    print_info(f"Downloaded complete test logs to: {local_log_path}")
        except Exception as e:
            print_error(f"Failed to collect logs: {str(e)}")
        finally:
            if conn is not None:
                conn.close()
        
        return success

def step_fetch_repo(node: str, initial_key_path: str, user: str, commit_id: str) -> bool:
    """Fetch and checkout the specified commit on the remote node"""
    print_step_header(f"Fetching repository on {node}")
    
    try:
        with Connection(
            host=node,
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
        ) as conn:
            # Set environment variables
            conn.config.run.env = {
                'JAVA_HOME': '/usr/lib/jvm/java-11-openjdk-arm64',
                'CHUKONU_HOME': '/root/chukonu/install',
                'LD_LIBRARY_PATH': '/root/chukonu/install/lib:/tmp/cache',
                'CHUKONU_TEMP': '/tmp',
                'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
            }
            
            # Create necessary directories
            conn.run("mkdir -p /tmp/staging /tmp/cache /root/chukonu/build /root/chukonu/install")
            
            if commit_id:
                print_info(f"Checking out commit: {commit_id}")
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    transient=True
                ) as progress:
                    progress.add_task("[cyan]Updating repository...", total=None)
                    conn.run(f"cd /root/chukonu && git pull && git checkout {commit_id}")
            
            print_success(f"Repository updated on {node}")
            return True
            
    except Exception as e:
        print_error(f"Error configuring node {node}: {e}")
        return False

def step_create_instances(manager: ECSInstanceManager, args) -> list:
    """Create ECS instances with progress tracking"""
    print_step_header(f"Creating {args.num_instances} instances")
    
    instance_zone = args.instance_zone if args.instance_zone else f"{args.region}a"
    created_instances_details = []
    
    if args.use_ip:
        print_info(f"Allocating EIPs for {args.num_instances} instances...")
        manager.eip_list = manager.eip_manager.create_eips(
            args.num_instances, 
            f"{args.run_number}_{args.task_type}",
            args.bandwidth
        )
        
        if not manager.eip_list or len(manager.eip_list) < args.num_instances:
            print_error("EIP allocation failed or insufficient EIPs, cannot proceed")
            return []
        
        save_eips_to_file(f"{args.run_number}_{args.task_type}", manager.eip_list)
        
        # Display EIP information
        eip_table = Table(title="Allocated EIPs", show_header=True, header_style="bold cyan")
        eip_table.add_column("Index", style="dim", justify="right")
        eip_table.add_column("EIP ID")
        eip_table.add_column("IP Address")
        for i, eip in enumerate(manager.eip_list, 1):
            eip_table.add_row(str(i), eip['id'], eip['ip'])
        console.print(Panel(eip_table))
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        with ThreadPoolExecutor(max_workers=min(args.num_instances, 10)) as executor:
            futures = {}
            for i in range(args.num_instances):
                task_id = progress.add_task(f"Instance {i+1}/{args.num_instances}", total=100, start=False)
                progress.update(task_id, completed=0)

                eip_id = manager.eip_list[i]['id'] if args.use_ip and i < len(manager.eip_list) else None
                
                future = executor.submit(
                    manager.create_instance,
                    progress, task_id, 
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
                        progress.update(task_id, description=f"[red]Instance {instance_index} failed", completed=100)
                except Exception as e:
                    progress.update(task_id, description=f"[red]Instance {instance_index} error", completed=100)
                    print_error(f"Error processing instance {instance_index}: {e}")

    return created_instances_details

def step_delete_resources(manager: ECSInstanceManager, instances: list, args):
    """Delete created resources (instances and EIPs)"""
    print_step_header("Cleaning up resources", style="bold red")
    
    if not instances:
        print_warning("No instances to delete")
        return False
    
    server_ids_to_delete = [inst['id'] for inst in instances]
    eip_ids_to_delete = [inst['eip_id'] for inst in instances if inst.get('eip_id')]
    
    wait_seconds = 10
    print_info(f"Waiting {wait_seconds} seconds before deleting {len(server_ids_to_delete)} instances...")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        transient=True
    ) as progress:
        task = progress.add_task("[yellow]Waiting to delete...", total=wait_seconds)
        for _ in range(wait_seconds):
            time.sleep(1)
            progress.update(task, advance=1)
    
    # Delete instances
    all_deleted = manager.delete_instances(server_ids_to_delete)
    
    # Delete EIPs
    if eip_ids_to_delete:
        print_info("Deleting associated EIPs...")
        manager.eip_manager.delete_eips(eip_ids_to_delete)
        
        # Clean up files
        info_path = f"./cache/{args.run_number}_{args.task_type}_ip_info.txt"
        if os.path.exists(info_path):
            os.remove(info_path)
            print_info(f"Removed file: {info_path}")
    
    return all_deleted

def display_instance_table(instances: list):
    """Display a table of created instances"""
    if not instances:
        print_warning("No instances to display")
        return
    
    table = Table(title="Created Instances", show_header=True, header_style="bold green")
    table.add_column("Index", style="dim", justify="right")
    table.add_column("Name")
    table.add_column("ID")
    table.add_column("Private IP")
    table.add_column("Public IP")
    table.add_column("Status")
    
    for inst in sorted(instances, key=lambda x: x['index']):
        table.add_row(
            str(inst['index']),
            inst['name'],
            inst['id'],
            inst.get('private_ip', 'N/A'),
            inst.get('public_ip', 'N/A'),
            inst['status']
        )
    
    console.print(Panel(table))

def main():
    parser = argparse.ArgumentParser(
        description='Huawei Cloud ECS Instance Management Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Example:
  python ecs_manager_create_delete.py --ak YOUR_AK --sk YOUR_SK --region cn-east-3 \\
    --vpc-id vpc-123 --instance-type kc1.large.4 --key-pair my-key \\
    --security-group-id sg-xxxx --subnet-id subnet-yyyy \\
    --run-number 1002 --task-type test --actor tester --num-instances 3
""")
    parser.add_argument('--ak', required=True, help='Huawei Cloud Access Key')
    parser.add_argument('--sk', required=True, help='Huawei Cloud Secret Key')
    parser.add_argument('--region', required=True, help='Region (e.g. cn-north-4)')
    parser.add_argument('--vpc-id', required=True, help='VPC ID')
    parser.add_argument('--num-instances', type=int, default=1, help='Number of instances to create')
    parser.add_argument('--instance-type', required=True, help='Instance type (e.g. s6.large.2)')
    parser.add_argument('--instance-zone', help='Availability zone (e.g. cn-north-4a, default: <region>a)', default=None)
    parser.add_argument('--ami', help='Image ID (e.g. CentOS 7.x)', default="04b5ea14-da35-47de-8467-66808dd62007")
    parser.add_argument('--key-pair', required=True, help='SSH key pair name')
    parser.add_argument('--security-group-id', required=True, help='Security group ID')
    parser.add_argument('--subnet-id', required=True, help='Subnet ID')
    parser.add_argument('--run-number', required=True, help='Run number')
    parser.add_argument('--task-type', required=True, help='Task type')
    parser.add_argument('--timeout-hours', default="1", help='Auto-termination time (hours, default 1)')
    parser.add_argument('--actor', required=True, help='Operator')
    parser.add_argument('--use-ip', action='store_true', help='Allocate public IP (default: false)', default=False)
    parser.add_argument('--commit-id', default="", help='Chukonu commit ID')
    parser.add_argument('--bandwidth', type=int, default=5, help='EIP bandwidth (Mbps)')
    args = parser.parse_args()

    manager = ECSInstanceManager(args.ak, args.sk, args.region)
    
    # Step 1: Create instances
    created_instances = step_create_instances(manager, args)
    
    if not created_instances:
        print_error("Test failed: No instances created successfully")
        if args.use_ip and manager.eip_list:
            print_warning("Cleaning up allocated EIPs...")
            manager.eip_manager.delete_eips([eip['id'] for eip in manager.eip_list])
        return

    print_success(f"Total {len(created_instances)}/{args.num_instances} instances created successfully")
    
    if len(created_instances) < args.num_instances:
        print_warning(f"Note: {args.num_instances - len(created_instances)} instances failed to create")

    # Save instance information
    info_file = manager.save_instances_info(
        f"{args.run_number}_{args.task_type}",
        created_instances
    )
    
    initial_key_path = "/root/schedule/KeyPair-loacl.pem"
    
    # Display instance table
    display_instance_table(created_instances)
    
    # Step 2: Fetch repository
    if created_instances and created_instances[0].get('public_ip'):
        step_fetch_repo(created_instances[0]['public_ip'], initial_key_path, "root", args.commit_id)
        
        # Step 3: Build wheel
        step_build_wheel(created_instances[0]['public_ip'], initial_key_path, "root", args.task_type)
    
    # Step 4: Clean up resources
    all_deleted = step_delete_resources(manager, created_instances, args)
    
    if all_deleted:
        if len(created_instances) == args.num_instances:
            print_success(f"Test completed: {len(created_instances)} instances created and deleted successfully!")
        else:
            print_success(f"Test partially completed: {len(created_instances)}/{args.num_instances} instances created and deleted successfully!")
    else:
        print_error(f"Test failed: Some or all instances (total {len(created_instances)} attempted) failed to delete")

if __name__ == "__main__":
    main()