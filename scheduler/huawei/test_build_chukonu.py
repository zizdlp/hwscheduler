from fabric import Connection
import argparse
from datetime import datetime

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
            
            # 在/tmp下创建带时间戳的测试日志目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            test_logs_dir = f"/tmp/chukonu_test_logs_{timestamp}"
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
            
            # Run C++ tests and capture logs to /tmp
            print(f"Running C++ tests on {node} and saving logs to {test_logs_dir}/ctest.log")
            ctest_result = conn.run(
                'cd /root/chukonu/build && ctest --output-on-failure',
                warn=True,
                hide=False,
                pty=True  # Use pty for interactive programs
            )
            conn.run(f"cat > {test_logs_dir}/ctest.log << 'EOF'\n{ctest_result.stdout}\nEOF")
            if ctest_result.stderr:
                conn.run(f"echo '\nSTDERR:\n{ctest_result.stderr}' >> {test_logs_dir}/ctest.log")
            
            # Run Scala tests and capture logs to /tmp
            print(f"Running Scala tests on {node} and saving logs to {test_logs_dir}/sbt_test.log")
            sbt_test_result = conn.run(
                'cd /root/chukonu/scala && ~/.local/share/coursier/bin/sbt test',
                warn=True,
                hide=False,
                pty=True  # Use pty for interactive programs
            )
            conn.run(f"cat > {test_logs_dir}/sbt_test.log << 'EOF'\n{sbt_test_result.stdout}\nEOF")
            if sbt_test_result.stderr:
                conn.run(f"echo '\nSTDERR:\n{sbt_test_result.stderr}' >> {test_logs_dir}/sbt_test.log")
            
            # Compress test logs in /tmp for easy download
            conn.run(f"tar -czf {test_logs_dir}.tar.gz -C {test_logs_dir} .")
            print(f"Test logs archived to: {test_logs_dir}.tar.gz")
            
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
    
    success = test_build_chukonu(args.node, args.key_path, args.user)
    if success:
        print(f"Successfully built Chukonu on {args.node}")
    else:
        print(f"Failed to build Chukonu on {args.node}")
        exit(1)