from fabric import Connection
from io import StringIO
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess

def generate_ssh_key_locally(key_path="~/.ssh/cluster_key"):
    """
    在宿主机生成SSH密钥对
    """
    # 扩展本地路径中的~为用户目录
    expanded_key_path = os.path.expanduser(key_path)
    print(f"DEBUG: Expanded key path: {expanded_key_path}")  # 添加调试输出

    private_key = expanded_key_path
    public_key = f"{private_key}.pub"

    # 检查是否已存在密钥
    if os.path.exists(private_key):
        print(f"SSH key already exists at {private_key}")
        with open(public_key, 'r') as f:
            public_key_content = f.read().strip()
        return private_key, public_key_content

    # 创建目录（如果不存在）
    os.makedirs(os.path.dirname(private_key), exist_ok=True)
    print(f"DEBUG: Directory created: {os.path.dirname(private_key)}")  # 添加调试输出

    # 生成SSH密钥对（非交互式）
    print("DEBUG: Running ssh-keygen command...")  # 添加调试输出
    subprocess.run(f'ssh-keygen -t rsa -N "" -f {private_key}', shell=True, check=True)

    # 设置正确的权限
    os.chmod(private_key, 0o600)
    os.chmod(public_key, 0o644)

    print(f"Generated SSH key pair at {private_key}")

    with open(public_key, 'r') as f:
        public_key_content = f.read().strip()
    return private_key, public_key_content
def upload_ssh_keys(conn, local_private_key_path, public_key_content, remote_key_path="~/.ssh/cluster_key"):
    """
    上传SSH密钥到远程节点（带详细错误分段处理）
    """
    # 确保使用绝对路径
    local_private_key_path = os.path.abspath(os.path.expanduser(local_private_key_path))
    remote_key_path = os.path.expanduser(remote_key_path)  # 处理远程路径中的~

    print(f"DEBUG: 上传私钥从 {local_private_key_path} 到 {conn.host}:{remote_key_path}")

    try:
        # 1. 上传私钥
        try:
            with open(local_private_key_path, 'rb') as f:
                conn.put(f, remote=remote_key_path)
            print(f"DEBUG: 私钥上传成功到 {conn.host}")
        except Exception as e:
            raise RuntimeError(f"私钥上传失败: {str(e)} (可能原因: 本地文件不可读/权限问题/路径错误)")

        # 2. 上传公钥
        try:
            public_key_io = StringIO(public_key_content)
            conn.put(public_key_io, remote=f"{remote_key_path}.pub")
            print(f"DEBUG: 公钥上传成功到 {conn.host}")
        except Exception as e:
            raise RuntimeError(f"公钥上传失败: {str(e)} (可能原因: 内存内容无效/远程路径问题)")

        # 3. 配置authorized_keys
        try:
            # 先确保authorized_keys存在
            conn.run("touch ~/.ssh/authorized_keys")
            # 避免重复添加
            conn.run(f"grep -q -F '{public_key_content}' ~/.ssh/authorized_keys || echo '{public_key_content}' >> ~/.ssh/authorized_keys")
            print(f"DEBUG: authorized_keys配置成功")
        except Exception as e:
            raise RuntimeError(f"authorized_keys配置失败: {str(e)} (可能原因: SSH目录不存在/权限不足)")

        # 4. 设置权限
        try:
            conn.run(f"chmod 600 {remote_key_path}")
            conn.run(f"chmod 644 {remote_key_path}.pub")
            conn.run("chmod 600 ~/.ssh/authorized_keys")
            print(f"DEBUG: 权限设置成功")
        except Exception as e:
            raise RuntimeError(f"权限设置失败: {str(e)} (可能原因: 文件不存在/权限不足)")

        return True

    except Exception as e:
        print(f"ERROR: 节点 {conn.host} 配置失败 - {str(e)}")
        return False
def configure_ssh_config(conn, remote_key_path="~/.ssh/cluster_key"):
    """
    配置SSH客户端选项以加快连接速度
    """
    remote_key_path = os.path.expanduser(remote_key_path)
    ssh_config = "~/.ssh/config"
    expanded_ssh_config = os.path.expanduser(ssh_config)
    config_content = f"""
Host *
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
    ConnectTimeout 5
    IdentityFile {remote_key_path}
    """
    print("hello world=============================")
    # 使用StringIO来写入配置
    config_io = StringIO(config_content)
    conn.put(config_io, remote=expanded_ssh_config)
    conn.run(f"chmod 600 {expanded_ssh_config}", hide=True)

    print(f"Configured SSH client options on {conn.host}")

def setup_passwordless_ssh(hosts, initial_key_path, user="root", local_key_path="~/.ssh/cluster_key", remote_key_path="~/.ssh/cluster_key"):
    """
    设置多节点之间的SSH免密登录

    Args:
        hosts (list): 包含所有节点信息的字典列表，每个字典至少包含'hostname'字段
        initial_key_path (str): 用于初始连接节点的私钥路径
        user (str): SSH用户名
        local_key_path (str): 本地生成的密钥路径
        remote_key_path (str): 远程节点上的密钥路径
    """
    # 在宿主机生成SSH密钥对
    print("=== Generating SSH key pair on local machine ===")
    local_private_key_path, public_key_content = generate_ssh_key_locally(local_key_path)

    # 分发密钥到所有节点
    print("\n=== Distributing SSH keys to all nodes ===")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for node in hosts:
            futures.append(executor.submit(
                lambda n: configure_node(n, initial_key_path, user, local_private_key_path, public_key_content, remote_key_path), node
            ))

        # 等待所有任务完成
        results = [f.result() for f in futures]

    if all(results):
        print("\n=== SSH passwordless setup completed successfully ===")
        return True
    else:
        print("\n=== SSH passwordless setup completed with errors ===")
        return False

def configure_node(node, initial_key_path, user, local_private_key_path, public_key_content, remote_key_path):
    """
    配置单个节点
    """
    try:
        with Connection(
            host=node['hostname'],
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
        ) as conn:
            # 上传SSH密钥
            upload_ssh_keys(conn, local_private_key_path, public_key_content, remote_key_path)

            # 配置SSH客户端选项
            configure_ssh_config(conn, remote_key_path)

            return True
    except Exception as e:
        print(f"Error configuring node {node['hostname']}: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Setup passwordless SSH between multiple nodes using a single key pair.')
    parser.add_argument('--hosts', required=True, nargs='+',
                       help='List of hostnames or IP addresses of the nodes.')
    parser.add_argument('--key_path', required=True,
                       help='Path to the private key file for initial connection.')
    parser.add_argument('--user', default='root',
                       help='Username to connect as (default: root).')
    parser.add_argument('--local_key', default='~/.ssh/cluster_key',
                       help='Path to store the generated SSH key pair on local machine (default: ~/.ssh/cluster_key).')
    parser.add_argument('--remote_key', default='~/.ssh/cluster_key',
                       help='Path to store the SSH key pair on remote nodes (default: ~/.ssh/cluster_key).')

    args = parser.parse_args()

    # 准备节点列表
    nodes = [{'hostname': host} for host in args.hosts]

    # 执行免密登录设置
    success = setup_passwordless_ssh(
        nodes,
        args.key_path,
        args.user,
        args.local_key,
        args.remote_key
    )

    if success:
        print("\nVerification:")
        # 随机选择一个节点进行验证
        test_node = nodes[0]
        try:
            with Connection(
                host=test_node['hostname'],
                user=args.user,
                connect_kwargs={"key_filename": args.key_path},
            ) as conn:
                # 尝试SSH到其他节点
                for node in nodes[1:3]:  # 只测试前几个节点
                    print(f"Testing SSH from {test_node['hostname']} to {node['hostname']}...")
                    result = conn.run(f"ssh -i {args.remote_key} -o BatchMode=yes {node['hostname']} 'echo Success from $(hostname)'", hide=True)
                    print(result.stdout.strip())
        except Exception as e:
            print(f"Verification failed: {e}")
    else:
        print("Setup failed. Please check the error messages above.")