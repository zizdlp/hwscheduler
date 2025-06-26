# coding: utf-8
from fabric import Connection
from concurrent.futures import ThreadPoolExecutor
import os
import time
from concurrent.futures import as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
from huaweicloudsdkecs.v2 import *
from huaweicloudsdkeip.v2 import *
from hwscheduler.huawei.ecs_manager import ECSInstanceManager, save_eips_to_file
import time
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
    
    

def step_fetch_repo(node: str, initial_key_path: str, user: str, commit_id: str = None, branch_name: str = None, tag: str = None) -> bool:
    """Fetch and checkout the specified commit/tag/branch on the remote node (in order of priority: commit > tag > branch)"""
    print_step_header(f"Fetching repository on {node}")
    
    try:
        max_attempts = 10
        retry_delay = 5  # seconds between retries
        
        # Initialize connection outside the try block
        conn = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                # Create a new connection for each attempt
                conn = Connection(
                    host=node,
                    user=user,
                    connect_kwargs={"key_filename": initial_key_path},
                    connect_timeout=10  # Add connection timeout
                )
                
                # Test the connection
                print(f"[step_fetch_repo] Testing SSH connection to {node} (attempt {attempt}/{max_attempts})...")
                result = conn.run("echo 'Connection test successful'", hide=True, warn=True)
                
                if result.ok:
                    print(f"[step_fetch_repo] ✅ SSH connection to {node} established successfully")
                    break
                else:
                    print(f"[step_fetch_repo] ❌ Failed to connect to {node} (attempt {attempt})")
                    if attempt < max_attempts:
                        time.sleep(retry_delay)
                        continue
            
            except Exception as e:
                print(f"[step_fetch_repo] ⚠ Connection attempt {attempt} failed with error: {str(e)}")
                if attempt < max_attempts:
                    time.sleep(retry_delay)
                    continue
        
        if conn is None:
            print_warning(f"Failed to establish SSH connection to {node} after {max_attempts} attempts")
            print_warning("Proceeding with operation despite connection issues")
            conn = Connection(
                host=node,
                user=user,
                connect_kwargs={"key_filename": initial_key_path},
                connect_timeout=30  # Longer timeout for the actual operation
            )
        
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
        
        # Always perform git pull first
        console.print("\n[bold]Updating repository...[/bold]")
        git_commands = [
            ("cd /root/chukonu && git pull && git checkout main", "Pull latest changes from origin"),
        ]
        
        # Add checkout command based on priority
        if commit_id:
            git_commands.extend([
                (f"cd /root/chukonu && git checkout {commit_id}", f"Checkout commit {commit_id}"),
            ])
        elif tag:
            git_commands.extend([
                (f"cd /root/chukonu && git fetch --tags", "Fetch tags from remote"),
                (f"cd /root/chukonu && git checkout tags/{tag}", f"Checkout tag {tag}"),
            ])
        elif branch_name:
            git_commands.extend([
                (f"cd /root/chukonu && git checkout {branch_name}", f"Checkout branch {branch_name}"),
                ("cd /root/chukonu && git pull", "Pull latest changes for branch"),
            ])
        
        # Always verify status
        git_commands.append(
            ("cd /root/chukonu && git status", "Verify repository status")
        )
        
        # Execute all commands
        for cmd, desc in git_commands:
            try:
                if not execute_command_with_logging(conn, cmd, description=desc):
                    print_warning(f"Command failed but continuing: {desc}")
            except Exception as e:
                print_warning(f"Exception during command execution (continuing): {str(e)}")
        
        print_success(f"Repository update attempted on {node}")
        return True
        
    except Exception as e:
        console.print_exception()
        return False
    finally:
        if conn is not None:
            conn.close()


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
