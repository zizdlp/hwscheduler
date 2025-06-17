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

def step_unitest_base(node: str, initial_key_path: str, user: str, task_name: str,script_path) -> bool:
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
        print_step_header(f"Run spark unitest {task_name} on {node}")
        
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
             "Create logs directory"),
            ('cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt package',"sbt package"),
            ('cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt assembly',"sbt assembly"),
            ('cd /root/chukonu/build && cmake .. -DCMAKE_BUILD_TYPE=Debug -DWITH_ASAN=OFF -DWITH_JEMALLOC=OFF -DCMAKE_INSTALL_PREFIX="$CHUKONU_HOME"',"build chukonu"),
            ('cd /root/chukonu/build && make install -j4',"build && install chukonu"),
            ('cd /root/spark && ~/.local/share/coursier/bin/sbt package', 'sbt_build'),
            ('cd /root/spark/python && python3 setup.py sdist', 'pyspark_build'),
            ('cd /root/spark/python && pip install dist/pyspark-3.4.4.dev0.tar.gz', 'pyspark_install')
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
            conn.put(script_path, "/root/spark/unitest_spark.sh")
            console.print("[green]✓ Build script uploaded successfully[/green]")
            
            # Verify file exists
            if not execute_command_with_logging(conn,
                                              f"test -f /root/spark/unitest_spark.sh",
                                              description="Verify build script exists"):
                return False
        except Exception as e:
            console.print(f"[red]✗ Failed to upload build script: {e}[/red]")
            return False
        
        # Build commands with logging
        console.print("\n[bold]Starting test process...[/bold]")
        build_commands = [
            (f"chmod +x /root/spark/unitest_spark.sh",
             "Make build script executable",
             f"{test_logs_dir}/chmod.log"),
             
            # (f"cd /root/spark && bash unitest_spark.sh {task_name} > {test_logs_dir}/unitest_base.log 2>&1",
            #  "unitest base",
            #  f"{test_logs_dir}/unitest_base.log")
        ]
        
        for cmd, desc, log_file in build_commands:
            if not execute_command_with_logging(conn, cmd, log_file, description=desc):
                success = False
                break
        
        if not success:
            return False
        result = conn.run(
            f'cd /root/spark && bash unitest_spark.sh {task_name} > {test_logs_dir}/unitest_base.log 2>&1',
            warn=True
        )
        
        if not result.ok:
            print(f"Warning: Command failed on {node}: {cmd}")

        # 分析日志文件并生成JSON
        json_log = f"{test_logs_dir}/{task_name}.json"
        awk_script = '''awk '
            BEGIN {
                print "{";
                capture = 0;
            }
            /Tests:/ {
                match($0, /succeeded ([0-9]+), failed ([0-9]+), canceled ([0-9]+), ignored ([0-9]+), pending ([0-9]+)/, arr);
                print "  \\"succeeded\\": \\"" arr[1] "\\",";
                print "  \\"failed\\": \\"" arr[2] "\\",";
                print "  \\"canceled\\": \\"" arr[3] "\\",";
                print "  \\"ignored\\": \\"" arr[4] "\\",";
                print "  \\"pending\\": \\"" arr[5] "\\"";
            }
            END {
                print "}";
            }
        ' ''' + f"{test_logs_dir}/unitest_base.log > {json_log}"
        
        conn.run(awk_script)
    
        # 收集测试结果文件 (TEST*.xml 和 hs_err*.log)
        print("\nCollecting test result files...")
        unitest_xml_dir = f"{test_logs_dir}/unitest_xml"
        conn.run(f"mkdir -p {unitest_xml_dir}")
        
        # 使用find命令查找并复制测试结果文件
        collect_cmd = f"""
        TMP_DIR=$(mktemp -d)
        sudo find /root/spark -type f \( \
            -name 'TEST*.xml' \
            -o -name 'hs_err*.log' \
        \) -exec cp --parents {{}} "$TMP_DIR/" \;
        
        # 如果有文件被找到，打包它们
        if [ "$(ls -A $TMP_DIR)" ]; then
            tar -czf {unitest_xml_dir}/unitest_xml.tar.gz -C $TMP_DIR .
        else
            echo "No test result files found" > {unitest_xml_dir}/no_files_found.txt
        fi
        rm -rf $TMP_DIR
        """
        
        conn.run(collect_cmd)

        # 下载文件到本地
        local_cache_dir = "./cache"
        os.makedirs(local_cache_dir, exist_ok=True)
        
        # 下载JSON结果
        local_json_path = os.path.join(local_cache_dir, f"test_results_{task_name}_{timestamp}.json")
        conn.get(json_log, local_json_path)
        print(f"Downloaded test results JSON to: {local_json_path}")
        
        # 下载单元测试XML和错误日志
        local_xml_path = os.path.join(local_cache_dir, f"unitest_xml_{task_name}_{timestamp}.tar.gz")
        conn.get(f"{unitest_xml_dir}/unitest_xml.tar.gz", local_xml_path)
        print(f"Downloaded unit test XML files to: {local_xml_path}")
        
        # 读取并打印JSON内容
        json_result = conn.run(f"cat {json_log}", hide=True)
        print("\nTest Results JSON:")
        print(json_result.stdout)
        
        # Compress all test logs
        conn.run(f"tar -czf {test_logs_dir}.tar.gz -C {test_logs_dir} .")
        print(f"All test logs archived to: {test_logs_dir}.tar.gz")
        
        # Download the complete log archive
        local_log_path = os.path.join(local_cache_dir, f"chukonu_test_logs_{task_name}_{timestamp}.tar.gz")
        conn.get(f"{test_logs_dir}.tar.gz", local_log_path)
        print(f"Downloaded complete test logs to: {local_log_path}")


        print_success(f"spark unitest {task_name} successfully on {node}")
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
    parser.add_argument('--tag', default="", help='Chukonu commit Tag')
    parser.add_argument('--branch-name', default="", help='Chukonu commit branch')
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
        if not step_fetch_repo(first_instance['public_ip'], args.key_path, "root", args.commit_id,args.branch_name,args.tag):
            console.print("[red]Aborting due to repository fetch failure[/red]")
            step_delete_resources(manager, created_instances, args)
            return
        
        # Build wheel
        if not step_unitest_base(first_instance['public_ip'], args.key_path, "root", args.task_type,args.script_path):
            console.print("[red]Aborting due to build failure[/red]")
            # step_delete_resources(manager, created_instances, args)
            return
    
    # Step 3: Clean up resources
    # all_deleted = step_delete_resources(manager, created_instances, args)
    
    # if all_deleted:
    #     if len(created_instances) == args.num_instances:
    #         print_success(f"Test completed: {len(created_instances)} instances created and deleted successfully!")
    #     else:
    #         print_success(f"Test partially completed: {len(created_instances)}/{args.num_instances} instances created and deleted successfully!")
    # else:
    #     print_error(f"Test failed: Some or all instances (total {len(created_instances)} attempted) failed to delete")

if __name__ == "__main__":
    main()