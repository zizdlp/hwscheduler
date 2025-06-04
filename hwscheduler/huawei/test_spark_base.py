from fabric import Connection
import argparse
from datetime import datetime
import os
import time
def test_spark_base(node, initial_key_path, user,task_name):
    """
    Build and install Chukonu on the specified node
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
            test_logs_dir = f"/tmp/chukonu_test_logs_{timestamp}"
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
            
            # Run C++ tests with comprehensive logging
            # Run C++ tests with comprehensive logging
            ctest_log = f"{test_logs_dir}/{task_name}.log"
            print(f"Running C++ tests on {node} and saving logs to {ctest_log}")

            # First create an empty log file to ensure it exists
            conn.run(f"touch {ctest_log}")

            # Run the command with proper output handling
            # Using tee to capture output while still seeing it in real-time
            # Using nohup to prevent hanging if the connection drops
            result = conn.run(
                f'cd /root/spark && bash -c "./dev/run-tests --parallelism 1 --modules {task_name} > {ctest_log} 2>&1"'
            )

         
            # Verify test results and print statistics
            print(f"\nChecking test results in {ctest_log}...")

            # Extract and print test statistics
            stats_cmd = (
                f"grep -E 'Total number of tests run:|Tests: succeeded|All tests passed' {ctest_log} || true"
            )
            stats_result = conn.run(stats_cmd, hide=True)

            if not stats_result.stdout.strip():
                print("No test statistics found in log file")
                return False

            # Print the statistics
            print("\nTest Statistics:")
            print(stats_result.stdout)

            # Check for success conditions
            success_check = conn.run(
                f"grep -q 'All tests passed.' {ctest_log} && "
                f"grep -q 'Tests: succeeded [0-9]+, failed 0, canceled 0, ignored [0-9]+, pending 0' {ctest_log} || true",
                hide=True
            )

            if not success_check.ok or not success_check.stdout.strip():
                print("\nTests failed based on success criteria")
                return False

            print("\nAll tests passed successfully")
            
            # Compress test logs
            conn.run(f"tar -czf {test_logs_dir}.tar.gz -C {test_logs_dir} .")
            print(f"Test logs archived to: {test_logs_dir}.tar.gz")
            
            # Download the log archive
            local_cache_dir = "./cache"
            os.makedirs(local_cache_dir, exist_ok=True)
            local_log_path = os.path.join(local_cache_dir, f"chukonu_test_logs_{timestamp}.tar.gz")
            conn.get(f"{test_logs_dir}.tar.gz", local_log_path)
            print(f"Downloaded test logs to: {local_log_path}")
            
            return True
            
    except Exception as e:
        print(f"Error configuring master node {node}: {e}")
        return False
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build and install Chukonu on remote node')
    parser.add_argument('--node', required=True, help='Remote node hostname or IP')
    parser.add_argument('--key_path', required=True, help='Path to SSH private key')
    parser.add_argument('--user', default="root", help='Remote user (default: root)')
    parser.add_argument('--task-name',required=True, help='哪个测试')
    args = parser.parse_args()
    
    success = test_spark_base(args.node, args.key_path, args.user,args.task_name)
    if success:
        print(f"Successfully built Chukonu on {args.node}")
    else:
        print(f"Failed to build Chukonu on {args.node}")
        exit(1)