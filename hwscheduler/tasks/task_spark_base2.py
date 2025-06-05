# coding: utf-8
# 在文件顶部添加新的import
from fabric import Connection
from concurrent.futures import ThreadPoolExecutor
import os

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from huaweicloudsdkecs.v2 import *
from huaweicloudsdkeip.v2 import *
from hwscheduler.huawei.ecs_manager import ECSInstanceManager,save_eips_to_file
console = Console()

# 首先定义不同任务对应的命令模板
def get_test_command(task_name):
    if task_name == "hive-1":
        return './dev/run-tests --parallelism 1 --modules hive --included-tags "org.apache.spark.tags.HivePartOneTest,org.apache.spark.tags.HivePartTwoTest"'
    elif task_name == "hive-2":
        return './dev/run-tests --parallelism 1 --modules hive --included-tags org.apache.spark.tags.SlowHiveTest'
    elif task_name == "hive-3":
        return './dev/run-tests --parallelism 1 --modules hive --excluded-tags "org.apache.spark.tags.HivePartOneTest,org.apache.spark.tags.HivePartTwoTest,org.apache.spark.tags.SlowHiveTest"'
    elif task_name == "hive-thriftserver-1":
        return './dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartOneTest'
    elif task_name == "hive-thriftserver-2":
        return './dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartTwoTest'
    elif task_name == "hive-thriftserver-3":
        return './dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartThreeTest'
    elif task_name == "hive-thriftserver-4":
        return './dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartFourTest'
    elif task_name == "hive-thriftserver-5":
        return './dev/run-tests --parallelism 1 --modules hive-thriftserver --excluded-tags "org.apache.spark.tags.HiveThriftServerPartOneTest,org.apache.spark.tags.HiveThriftServerPartTwoTest,org.apache.spark.tags.HiveThriftServerPartThreeTest,org.apache.spark.tags.HiveThriftServerPartFourTest"'
    elif task_name == "sql-a-1":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartOneTest'
    elif task_name == "sql-a-2":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartTwoTest'
    elif task_name == "sql-a-3":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartThreeTest'
    elif task_name == "sql-a-4":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartFourTest'
    elif task_name == "sql-a-5":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartFiveTest'
    elif task_name == "sql-a-6":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartSixTest'
    elif task_name == "sql-a-7":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartZeroTest'
    elif task_name == "sql-b-1":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SlowSQLPartOneTest'
    elif task_name == "sql-b-2":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SlowSQLPartTwoTest'
    elif task_name == "sql-c-1":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartOneTest'
    elif task_name == "sql-c-2":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartTwoTest'
    elif task_name == "sql-c-3":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartThreeTest'
    elif task_name == "sql-c-4":
        return './dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartFourTest'
    elif task_name == "sql-c-5":
        return './dev/run-tests --parallelism 1 --modules sql --excluded-tags "org.apache.spark.tags.ExtendedSQLPartOneTest,org.apache.spark.tags.ExtendedSQLPartTwoTest,org.apache.spark.tags.ExtendedSQLPartThreeTest,org.apache.spark.tags.ExtendedSQLPartFourTest,org.apache.spark.tags.ExtendedSQLPartFiveTest,org.apache.spark.tags.SlowSQLPartOneTest,org.apache.spark.tags.SlowSQLPartTwoTest,org.apache.spark.tags.SplitSQLPartOneTest,org.apache.spark.tags.SplitSQLPartTwoTest,org.apache.spark.tags.SplitSQLPartThreeTest,org.apache.spark.tags.SplitSQLPartFourTest,org.apache.spark.tags.ExtendedSQLPartZeroTest,org.apache.spark.tags.ExtendedSQLPartSixTest"'
    else:
        # 默认情况，直接使用模块名
        return f'./dev/run-tests --parallelism 1 --modules {task_name}'


def test_spark_base(node, initial_key_path, user, task_name):
    """
    Build and install Chukonu on the specified node and collect test results
    """
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
            
            # Create timestamped test logs directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            test_logs_dir = f"/tmp/chukonu_spark_test_logs_{timestamp}"
            conn.run(f"mkdir -p {test_logs_dir}")
            
            commands = [
                # Build Spark
                ('cd /root/spark && ~/.local/share/coursier/bin/sbt package', 'sbt_build.log'),
                
                # Build and install PySpark
                ('cd /root/spark/python && python3 setup.py sdist', 'pyspark_build.log'),
                ('cd /root/spark/python && pip install dist/pyspark-3.4.4.dev0.tar.gz', 'pyspark_install.log')
            ]
            
            for cmd, logfile in commands:
                print(f"Executing on {node}: {cmd}")
                log_path = f"{test_logs_dir}/{logfile}"
                result = conn.run(f"{cmd} > {log_path} 2>&1", warn=True)
                if not result.ok:
                    print(f"Command failed on {node}: {cmd}")
                    print(f"Check log file at {log_path}")
                    return False
            
            # Run tests
            ctest_log = f"{test_logs_dir}/{task_name}.log"
            print(f"Running C++ tests on {node} and saving logs to {ctest_log}")
            conn.run(f"touch {ctest_log}")

            test_command = get_test_command(task_name)
            result = conn.run(
                f'cd /root/spark && bash -c "{test_command} > {ctest_log} 2>&1"',
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
            ' ''' + f"{ctest_log} > {json_log}"
            
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
            
            return True
            
    except Exception as e:
        print(f"Error configuring master node in test_spark_base: {node}: {e}")
        return False

def test_build_chukonu(node, initial_key_path, user):
    """
    Build and install Chukonu on the specified node
    """
    try:
        with Connection(
            host=node,
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
        ) as conn:
            # 设置环境变量（对所有后续命令生效）
            conn.config.run.env = {
                'JAVA_HOME': '/usr/lib/jvm/java-11-openjdk-arm64',
                'CHUKONU_HOME': '/root/chukonu/install',
                'LD_LIBRARY_PATH': '/root/chukonu/install/lib:/tmp/cache',
                'CHUKONU_TEMP': '/tmp',
                'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'  # 确保基本PATH设置
            }
            
            # 创建必要目录
            conn.run("mkdir -p /tmp/staging /tmp/cache /root/chukonu/build /root/chukonu/install")
            conn.run("cd /root/chukonu && git pull && git checkout v1.1.0")
            # 在/tmp下创建带时间戳的测试日志目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            test_logs_dir = f"/tmp/chukonu_build_chukonu_logs_{timestamp}"
            conn.run(f"mkdir -p {test_logs_dir}")
            
            commands = [
                # Build Scala components
                'cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt package',
                'cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt assembly',
                
                # Create build directory and configure
                'cd /root/chukonu/build && cmake .. -DCMAKE_BUILD_TYPE=Debug -DWITH_ASAN=OFF -DWITH_JEMALLOC=OFF -DCMAKE_INSTALL_PREFIX="$CHUKONU_HOME"',
                
                # Build and install
                'cd /root/chukonu/build && make install -j4',
            ]
            
            for cmd in commands:
                print(f"Executing on {node}: {cmd}")
                result = conn.run(cmd, warn=True)
                if not result.ok:
                    print(f"Command failed on {node}: {cmd}")
                    return False
            return True
            
    except Exception as e:
        print(f"Error configuring master node in test_build_chukonu: {node}: {e}")
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
    parser.add_argument('--key-path', required=True, help='SSH key pair path')
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
        test_build_chukonu(created_instances_details[0]['public_ip'],args.key_path,"root")
        test_spark_base(created_instances_details[0]['public_ip'],args.key_path,"root",args.task_type)
        
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