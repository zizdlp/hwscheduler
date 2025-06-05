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
from rich.syntax import Syntax
from huaweicloudsdkecs.v2 import *
from huaweicloudsdkeip.v2 import *
from hwscheduler.huawei.ecs_manager import ECSInstanceManager, save_eips_to_file

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

def execute_command_with_logging(conn, command: str, log_file: str = None, description: str = None) -> bool:
    """
    Execute a command with rich logging and status reporting
    
    Args:
        conn: Fabric Connection object
        command: Command to execute
        log_file: Path to log file (optional)
        description: Human-readable description of the command
        
    Returns:
        bool: True if command succeeded, False otherwise
    """
    try:
        # Print command header
        if description:
            console.print(f"\n[bold]Executing: [cyan]{description}[/cyan][/bold]")
        
        # Display the command (truncate if too long)
        cmd_display = command if len(command) < 60 else f"{command[:50]}...[truncated]...{command[-5:]}"
        console.print(f"[dim]Command: [white]{cmd_display}[/white][/dim]")
        
        # Start timer
        start_time = time.time()
        
        # Execute the command
        result = conn.run(command, warn=True, hide=True)
        
        # Calculate duration
        duration = time.time() - start_time
        mins, secs = divmod(duration, 60)
        time_str = f"{int(mins)}m {secs:.2f}s"
        
        if result.ok:
            console.print(f"[green]✓ Success (exit={result.exited}, time={time_str})[/green]")
            if log_file:
                console.print(f"[dim]Log saved to: {log_file}[/dim]")
            return True
        else:
            console.print(f"[red]✗ Failed (exit={result.exited}, time={time_str})[/red]")
            
            # Show error details if available
            if result.stderr:
                console.print(Panel(result.stderr, 
                                 title="[red]Error Output[/red]",
                                 border_style="red"))
            
            # Show log tail if available
            if log_file:
                tail_cmd = f"tail -n 20 {log_file}"
                tail_result = conn.run(tail_cmd, warn=True, hide=True)
                if tail_result.ok:
                    console.print(Panel(tail_result.stdout, 
                                     title=f"[red]Last 20 lines of {log_file}[/red]",
                                     border_style="red",
                                     subtitle=f"Full log at: {log_file}"))
            return False
            
    except Exception as e:
        console.print(f"[red]⚠ Exception during command execution: {str(e)}[/red]")
        console.print_exception()
        return False
def step_build_wheel(node: str, initial_key_path: str, user: str, task_name: str,script_path) -> bool:
    """
    Build and install Chukonu on the specified node and collect test results
    
    Args:
        node: Target node IP/hostname
        initial_key_path: Path to SSH key
        user: SSH user
        task_name: Name of the task for log naming
        
    Returns:
        bool: True if all steps succeeded, False otherwise
    """
    conn = None
    test_logs_dir = ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    success = True  # Assume success until proven otherwise
    
    try:
        print_step_header(f"Building wheel on {node}")
        
        # Establish connection
        console.print("\n[bold]Establishing SSH connection...[/bold]")
        try:
            conn = Connection(
                host=node,
                user=user,
                connect_kwargs={"key_filename": initial_key_path},
            )
            conn.open()
            console.print(f"[green]✓ Connected to {node} as {user}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Connection failed: {str(e)}[/red]")
            return False
        
        # Set environment variables
        console.print("\n[bold]Setting environment variables...[/bold]")
        conn.config.run.env = {
            'JAVA_HOME': '/usr/lib/jvm/java-11-openjdk-arm64',
            'CHUKONU_HOME': '/root/chukonu/install',
            'LD_LIBRARY_PATH': '/root/chukonu/install/lib:/tmp/cache',
            'CHUKONU_TEMP': '/tmp',
            'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        }
        console.print("[green]✓ Environment variables set[/green]")
        
        # Create necessary directories
        console.print("\n[bold]Creating directories...[/bold]")
        dir_commands = [
            ("mkdir -p /tmp/staging /tmp/cache /root/chukonu/build /root/chukonu/install",
             "Create base directories"),
            (f"mkdir -p /tmp/chukonu_spark_test_logs_{timestamp}",
             "Create logs directory")
        ]
        
        for cmd, desc in dir_commands:
            if not execute_command_with_logging(conn, cmd, description=desc):
                success = False
                break
        
        if not success:
            return False
        
        test_logs_dir = f"/tmp/chukonu_spark_test_logs_{timestamp}"
        
        # Upload build script
        console.print("\n[bold]Uploading build script...[/bold]")
        if not execute_command_with_logging(conn, 
                                         "mkdir -p /root",
                                         description="Ensure /root exists"):
            return False
            
        try:
            conn.put(script_path, "/root/build_wheel.sh")
            console.print("[green]✓ Build script uploaded successfully[/green]")
            
            # Verify file exists
            if not execute_command_with_logging(conn,
                                              "test -f /root/build_wheel.sh",
                                              description="Verify build script exists"):
                return False
        except Exception as e:
            console.print(f"[red]✗ Failed to upload build script: {e}[/red]")
            return False
        
        # Build commands with logging
        console.print("\n[bold]Starting build process...[/bold]")
        build_commands = [
            (f"chmod +x /root/build_wheel.sh",
             "Make build script executable",
             f"{test_logs_dir}/chmod.log"),
             
            (f"docker start manylinux",
             "Start Docker container",
             f"{test_logs_dir}/docker_start.log"),
             
            (f"docker exec manylinux /bin/bash -c 'bash /io/build_wheel.sh' > {test_logs_dir}/build_wheel.log 2>&1",
             "Build wheel in Docker container",
             f"{test_logs_dir}/build_wheel.log")
        ]
        
        for cmd, desc, log_file in build_commands:
            if not execute_command_with_logging(conn, cmd, log_file, description=desc):
                success = False
                break
        
        if not success:
            return False
        
        # Copy wheel file
        console.print("\n[bold]Collecting build artifacts...[/bold]")
        copy_cmd = f"cp /root/chukonu/python/wheelhouse/chukonu-1.1.0-py3-none-manylinux2014_aarch64.manylinux_2_17_aarch64.whl {test_logs_dir}/"
        if not execute_command_with_logging(conn, copy_cmd,
                                          description="Copy wheel file"):
            return False
        
        # Verify wheel file exists
        if not execute_command_with_logging(conn,
                                         f"test -f {test_logs_dir}/chukonu-1.1.0-py3-none-manylinux2014_aarch64.manylinux_2_17_aarch64.whl",
                                         description="Verify wheel file exists"):
            return False
        
        print_success(f"Wheel built successfully on {node}")
        return True
        
    except Exception as e:
        console.print_exception()
        return False
    finally:
        try:
            if conn is not None and conn.is_connected:
                if test_logs_dir and success:
                    console.print("\n[bold]Compressing and downloading logs...[/bold]")
                    
                    # Compress logs
                    compress_cmd = f"tar -czf {test_logs_dir}.tar.gz -C {test_logs_dir} ."
                    if not execute_command_with_logging(conn, compress_cmd,
                                                      description="Compress logs"):
                        return False
                    
                    # Download logs
                    local_cache_dir = "./logs"
                    os.makedirs(local_cache_dir, exist_ok=True)
                    local_log_path = os.path.join(local_cache_dir, 
                                                f"chukonu_logs_{task_name}_{timestamp}.tar.gz")
                    
                    try:
                        console.print(f"Downloading logs to {local_log_path}...")
                        conn.get(f"{test_logs_dir}.tar.gz", local_log_path)
                        console.print(f"[green]✓ Logs downloaded to: {local_log_path}[/green]")
                        
                        # Verify local file
                        if os.path.exists(local_log_path):
                            file_size = os.path.getsize(local_log_path) / (1024 * 1024)  # MB
                            console.print(f"[dim]Log file size: {file_size:.2f} MB[/dim]")
                        else:
                            console.print("[yellow]⚠ Warning: Local log file not found after download[/yellow]")
                    except Exception as e:
                        console.print(f"[red]✗ Failed to download logs: {e}[/red]")
        finally:
            if conn is not None:
                conn.close()
                console.print("[dim]SSH connection closed[/dim]")

def step_fetch_repo(node: str, initial_key_path: str, user: str, commit_id: str) -> bool:
    """Fetch and checkout the specified commit on the remote node"""
    print_step_header(f"Fetching repository on {node}")
    
    try:
        with Connection(
            host=node,
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
        ) as conn:
            # Print connection info
            console.print(f"\n[bold]Connected to [cyan]{node}[/cyan] as [cyan]{user}[/cyan][/bold]")
            
            # Set environment variables
            console.print("\n[bold]Setting environment variables...[/bold]")
            conn.config.run.env = {
                'JAVA_HOME': '/usr/lib/jvm/java-11-openjdk-arm64',
                'CHUKONU_HOME': '/root/chukonu/install',
                'LD_LIBRARY_PATH': '/root/chukonu/install/lib:/tmp/cache',
                'CHUKONU_TEMP': '/tmp',
                'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
            }
            console.print("[green]✓ Environment variables set[/green]")
            
            # Create necessary directories
            console.print("\n[bold]Creating directories...[/bold]")
            dir_commands = [
                ("mkdir -p /tmp/staging /tmp/cache /root/chukonu/build /root/chukonu/install",
                 "Create base directories")
            ]
            
            for cmd, desc in dir_commands:
                if not execute_command_with_logging(conn, cmd, description=desc):
                    return False
            
            if commit_id:
                console.print(f"\n[bold]Checking out commit: [cyan]{commit_id}[/cyan][/bold]")
                git_commands = [
                    ("cd /root/chukonu && git fetch origin",
                     "Fetch latest changes"),
                    (f"cd /root/chukonu && git checkout {commit_id}",
                     f"Checkout commit {commit_id}"),
                    ("cd /root/chukonu && git status",
                     "Verify repository status")
                ]
                
                for cmd, desc in git_commands:
                    if not execute_command_with_logging(conn, cmd, description=desc):
                        return False
            
            print_success(f"Repository updated on {node}")
            return True
            
    except Exception as e:
        console.print_exception()
        return False

def step_create_instances(manager: ECSInstanceManager, args) -> list:
    """Create ECS instances with progress tracking"""
    print_step_header(f"Creating {args.num_instances} instances")
    
    instance_zone = args.instance_zone if args.instance_zone else f"{args.region}a"
    created_instances_details = []
    
    if args.use_ip:
        console.print("\n[bold]Allocating EIPs...[/bold]")
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
        eip_table.add_column("Bandwidth (Mbps)")
        for i, eip in enumerate(manager.eip_list, 1):
            eip_table.add_row(str(i), eip['id'], eip['ip'], str(args.bandwidth))
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
                        progress.update(task_id, description=f"[green]Instance {instance_index} created", completed=100)
                    else:
                        progress.update(task_id, description=f"[red]Instance {instance_index} failed", completed=100)
                except Exception as e:
                    progress.update(task_id, description=f"[red]Instance {instance_index} error", completed=100)
                    console.print(f"[red]Error creating instance {instance_index}: {str(e)}[/red]")

    return created_instances_details

def step_delete_resources(manager: ECSInstanceManager, instances: list, args):
    """Delete created resources (instances and EIPs)"""
    print_step_header("Cleaning up resources", style="bold red")
    
    if not instances:
        print_warning("No instances to delete")
        return False
    
    server_ids_to_delete = [inst['id'] for inst in instances]
    eip_ids_to_delete = [inst['eip_id'] for inst in instances if inst.get('eip_id')]
    
    # Display summary of resources to delete
    summary_table = Table(title="Resources to Delete", show_header=True, header_style="bold yellow")
    summary_table.add_column("Resource Type")
    summary_table.add_column("Count")
    summary_table.add_row("Instances", str(len(server_ids_to_delete)))
    summary_table.add_row("EIPs", str(len(eip_ids_to_delete)))
    console.print(Panel(summary_table))
    
    wait_seconds = 10
    console.print(f"\n[bold yellow]Waiting {wait_seconds} seconds before deletion...[/bold yellow]")
    
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
    console.print("\n[bold]Deleting instances...[/bold]")
    all_deleted = manager.delete_instances(server_ids_to_delete)
    
    if all_deleted:
        console.print(f"[green]✓ Successfully deleted {len(server_ids_to_delete)} instances[/green]")
    else:
        console.print(f"[red]✗ Failed to delete some or all instances[/red]")
    
    # Delete EIPs
    if eip_ids_to_delete:
        console.print("\n[bold]Deleting associated EIPs...[/bold]")
        deleted_count = manager.eip_manager.delete_eips(eip_ids_to_delete)
        console.print(f"[green]✓ Deleted {deleted_count}/{len(eip_ids_to_delete)} EIPs[/green]")
        
        # Clean up files
        info_path = f"./cache/{args.run_number}_{args.task_type}_ip_info.txt"
        if os.path.exists(info_path):
            try:
                os.remove(info_path)
                console.print(f"[green]✓ Removed file: {info_path}[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠ Failed to remove file {info_path}: {e}[/yellow]")
    
    return all_deleted

def display_instance_table(instances: list):
    """Display a table of created instances"""
    if not instances:
        print_warning("No instances to display")
        return
    
    table = Table(title="Created Instances", show_header=True, header_style="bold green")
    table.add_column("Index", style="dim", justify="right")
    table.add_column("Name")
    table.add_column("ID", style="dim")
    table.add_column("Private IP")
    table.add_column("Public IP")
    table.add_column("Status")
    table.add_column("Created At")
    
    for inst in sorted(instances, key=lambda x: x['index']):
        table.add_row(
            str(inst['index']),
            inst['name'],
            inst['id'],
            inst.get('private_ip', 'N/A'),
            inst.get('public_ip', 'N/A'),
            inst['status'],
            inst.get('created_at', 'N/A')
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
    parser.add_argument('--key-path', required=True, help='SSH key pair path')
    parser.add_argument('--security-group-id', required=True, help='Security group ID')
    parser.add_argument('--subnet-id', required=True, help='Subnet ID')
    parser.add_argument('--run-number', required=True, help='Run number')
    parser.add_argument('--task-type', required=True, help='Task type')
    parser.add_argument('--timeout-hours', default="1", help='Auto-termination time (hours, default 1)')
    parser.add_argument('--actor', required=True, help='Operator')
    parser.add_argument('--use-ip', action='store_true', help='Allocate public IP (default: false)', default=False)
    parser.add_argument('--commit-id', default="", help='Chukonu commit ID')
    parser.add_argument('--bandwidth', type=int, default=5, help='EIP bandwidth (Mbps)')
    parser.add_argument('--script-path', required=True, help='build wheel sh')
    args = parser.parse_args()

    # Initialize manager
    console.print("\n[bold]Initializing ECS Instance Manager...[/bold]")
    manager = ECSInstanceManager(args.ak, args.sk, args.region)
    console.print(f"[green]✓ Manager initialized for region {args.region}[/green]")
    
    # Step 1: Create instances
    created_instances = step_create_instances(manager, args)
    if not created_instances:
        print_error("Test failed: No instances created successfully")
        if args.use_ip and manager.eip_list:
            console.print("\n[bold yellow]Cleaning up allocated EIPs...[/bold yellow]")
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
    console.print(f"[green]✓ Instance information saved to {info_file}[/green]")
    
    # Display instance table
    display_instance_table(created_instances)
    
    # Step 2: Fetch repository and build wheel on first instance
    if created_instances and created_instances[0].get('public_ip'):
        first_instance = created_instances[0]
        console.print(f"\n[bold]Using first instance: {first_instance['public_ip']}[/bold]")
        
        # Fetch repository
        if not step_fetch_repo(first_instance['public_ip'], args.key_path, "root", args.commit_id):
            console.print("[red]Aborting due to repository fetch failure[/red]")
            step_delete_resources(manager, created_instances, args)
            return
        
        # Build wheel
        if not step_build_wheel(first_instance['public_ip'], args.key_path, "root", args.task_type,args.script_path):
            console.print("[red]Aborting due to build failure[/red]")
            step_delete_resources(manager, created_instances, args)
            return
    
    # Step 3: Clean up resources
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