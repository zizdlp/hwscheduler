# coding: utf-8
from fabric import Connection
import os
import argparse
from datetime import datetime
from rich.console import Console
from huaweicloudsdkecs.v2 import *
from huaweicloudsdkeip.v2 import *
from hwscheduler.huawei.ecs_manager import ECSInstanceManager
from hwscheduler.utils.logging import print_step_header,print_success,print_warning,execute_command_with_logging,step_fetch_repo,print_error,step_create_instances,step_delete_resources,display_instance_table

console = Console()

def step_build_chukonu(node: str, initial_key_path: str, user: str, task_type: str) -> bool:
    """
    Build and install Chukonu on the specified node with rich logging
    
    Args:
        node: IP address or hostname of the node
        initial_key_path: Path to SSH key
        user: SSH username
        task_type: Task type identifier for logging
        
    Returns:
        bool: True if build succeeded, False otherwise
    """
    print_step_header(f"Building Chukonu on {node}")
    
    conn = None  # Initialize conn outside try block
    test_logs_dir = None  # Initialize test_logs_dir outside try block
    
    try:
        conn = Connection(
            host=node,
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
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
        print_success("Environment variables set")
        
        # Create necessary directories
        console.print("\n[bold]Creating directories...[/bold]")
        dir_commands = [
            ("mkdir -p /tmp/staging /tmp/cache /root/chukonu/build /root/chukonu/install",
             "Create base directories")
        ]
        
        for cmd, desc in dir_commands:
            if not execute_command_with_logging(conn, cmd, description=desc):
                return False
        
        # Create test logs directory with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_logs_dir = f"/tmp/chukonu_test_logs_{timestamp}"
        if not execute_command_with_logging(conn, f"mkdir -p {test_logs_dir}", 
                                         description=f"Create test logs directory: {test_logs_dir}"):
            return False
        
        # Build commands with descriptions
        build_commands = [
            # Build Scala components
            ('cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt package',
             "Build Scala package"),
            
            ('cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt assembly',
             "Create Scala assembly JAR"),
            
            # Configure CMake
            ('cd /root/chukonu/build && cmake .. -DCMAKE_BUILD_TYPE=Debug -DWITH_ASAN=OFF -DWITH_JEMALLOC=OFF -DCMAKE_INSTALL_PREFIX="$CHUKONU_HOME"',
             "Configure CMake build"),
            
            # Build and install
            ('cd /root/chukonu/build && make install -j4',
             "Build and install Chukonu"),
        ]
        
        # Execute build commands
        console.print("\n[bold]Starting Chukonu build process...[/bold]")
        for cmd, desc in build_commands:
            if not execute_command_with_logging(conn, cmd, description=desc):
                print_error(f"Build failed during: {desc}")
                return False
        
        # Run C++ tests
        console.print("\n[bold]Running C++ tests...[/bold]")
        ctest_log = f"{test_logs_dir}/ctest.log"
        ctest_cmd = f'cd /root/chukonu/build && ctest --output-on-failure > {ctest_log} 2>&1'
        
        if not execute_command_with_logging(conn, ctest_cmd, 
                                         log_file=ctest_log,
                                         description="Run C++ tests"):
            print_warning("Some C++ tests failed - check logs for details")
        
        # Run Scala tests
        console.print("\n[bold]Running Scala tests...[/bold]")
        sbt_log = f"{test_logs_dir}/sbt_test.log"
        sbt_cmd = f'cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt test > {sbt_log} 2>&1'
        
        if not execute_command_with_logging(conn, sbt_cmd,
                                         log_file=sbt_log,
                                         description="Run Scala tests"):
            print_warning("Some Scala tests failed - check logs for details")
        
        print_success(f"Chukonu build completed on {node}")
        return True
        
    except Exception as e:
        console.print_exception()
        return False
    finally:
        if conn is not None:
            try:
                if test_logs_dir:
                    console.print("\n[bold]Downloading logs...[/bold]")
                    
                    # Compress logs
                    compress_cmd = f"tar -czf {test_logs_dir}.tar.gz -C {test_logs_dir} ."
                    if not execute_command_with_logging(conn, compress_cmd,
                                                      description="Compress logs"):
                        return False
                    
                    # Download logs
                    local_cache_dir = "./logs"
                    os.makedirs(local_cache_dir, exist_ok=True)
                    local_log_path = os.path.join(local_cache_dir, 
                                                f"chukonu_logs_build_chukounu_{timestamp}.tar.gz")
                    
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
                conn.close()
                console.print("[dim]SSH connection closed[/dim]")

def main():
    parser = argparse.ArgumentParser(
        description='Huawei Cloud ECS Instance Management Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter
       )
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
        if not step_build_chukonu(first_instance['public_ip'], args.key_path, "root", args.task_type):
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