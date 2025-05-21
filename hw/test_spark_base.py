from fabric import Connection
import argparse
from datetime import datetime
import os

def test_spark_base(node, initial_key_path, user):
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
            ctest_log = f"{test_logs_dir}/ctest.log"
            print(f"Running C++ tests on {node} and saving logs to {ctest_log}")
            conn.run(
                f'cd /root/spark && ./dev/run-tests --parallelism 1 --modules kubernetes > {ctest_log} 2>&1',
                warn=True,
                pty=True
            )
            
            # Verify test results
            result = conn.run(f"grep -i 'fail' {ctest_log} | grep -v '0 Failures' || true", hide=True)
            if result.stdout.strip():
                print(f"Tests failed on {node}. Check {ctest_log} for details")
                return False
            
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
    args = parser.parse_args()
    
    success = test_spark_base(args.node, args.key_path, args.user)
    if success:
        print(f"Successfully built Chukonu on {args.node}")
    else:
        print(f"Failed to build Chukonu on {args.node}")
        exit(1)