from fabric import Connection
from io import StringIO
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess

def generate_ssh_key_locally(key_path="~/.ssh/cluster_key"):
    """
    在本地宿主机生成SSH密钥对
    """
    expanded_key_path = os.path.expanduser(key_path)
    print(f"DEBUG: Expanded key path: {expanded_key_path}")

    private_key = expanded_key_path
    public_key = f"{private_key}.pub"

    if os.path.exists(private_key) and os.path.exists(public_key):
        print(f"SSH key pair already exists at {private_key}")
        with open(public_key, 'r') as f:
            public_key_content = f.read().strip()
        return private_key, public_key_content

    os.makedirs(os.path.dirname(private_key), exist_ok=True)
    print(f"DEBUG: Directory created: {os.path.dirname(private_key)}")

    print("DEBUG: Running ssh-keygen command...")
    # -N "" 表示不设置密码
    subprocess.run(f'ssh-keygen -t rsa -b 2048 -N "" -f {private_key}', shell=True, check=True)

    os.chmod(private_key, 0o600) # 私钥权限为600
    os.chmod(public_key, 0o644) # 公钥权限为644

    print(f"Generated SSH key pair at {private_key}")

    with open(public_key, 'r') as f:
        public_key_content = f.read().strip()
    return private_key, public_key_content

def upload_file(conn, local_path, remote_path):
    """
    上传文件到远程节点
    """
    try:
        with open(local_path, 'rb') as f:
            conn.put(f, remote=remote_path)
        print(f"DEBUG: 文件 {local_path} 上传成功到 {conn.host}:{remote_path}")
        return True
    except Exception as e:
        # 更详细的错误信息
        if not os.path.exists(local_path):
            raise RuntimeError(f"文件上传失败: 本地文件不存在 {local_path}")
        raise RuntimeError(f"文件上传失败到 {conn.host}:{remote_path}: {str(e)} (可能原因: 权限问题/远程路径错误)")

def append_to_remote_file(conn, remote_file, content):
    """
    向远程文件追加内容，避免重复添加
    """
    try:
        # 使用 grep -F (fixed string) 和 -q (quiet) 检查内容是否存在，不存在则追加
        # 为了避免特殊字符问题，对内容进行转义，或者更安全的做法是分两步：先检查，再 echo
        # 这里为了简洁，直接使用echo，并假设内容不会包含危险shell字符
        # 对于SSH公钥，通常不会有问题。
        conn.run(f"mkdir -p $(dirname {remote_file}) && chmod 700 $(dirname {remote_file})", hide=True, warn=True) # 确保目录存在且权限正确
        conn.run(f"grep -q -F '{content}' {remote_file} || echo '{content}' >> {remote_file}", hide=True)
        conn.run(f"chmod 600 {remote_file}", hide=True) # 确保文件权限正确
        print(f"DEBUG: 内容追加到 {conn.host}:{remote_file} 成功")
        return True
    except Exception as e:
        raise RuntimeError(f"向 {conn.host}:{remote_file} 追加内容失败: {str(e)}")

def configure_ssh_config(conn, remote_key_path="~/.ssh/cluster_key"):
    """
    配置SSH客户端选项以加快连接速度和使用指定密钥
    """
    # Fabric 内部会处理 ~ 展开
    ssh_config_file = "~/.ssh/config"
    
    # 构建 Host * 配置，确保 IdentityFile 指向集群私钥
    config_content = f"""
Host *
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
    ConnectTimeout 10
    IdentityFile {remote_key_path}
    """
    print(f"DEBUG: Configuring SSH client options on {conn.host} for IdentityFile {remote_key_path}...")
    
    try:
        # 使用StringIO将字符串内容上传到远程文件
        config_io = StringIO(config_content.strip()) # strip() 去除首尾空白，避免写入空行
        conn.put(config_io, remote=ssh_config_file)
        conn.run(f"chmod 600 {ssh_config_file}", hide=True)
        print(f"Configured SSH client options on {conn.host} for IdentityFile {remote_key_path}")
    except Exception as e:
        print(f"Error configuring SSH client options on {conn.host}: {e}")

def configure_hosts_file(conn, hosts_map):
    """
    配置远程节点的 /etc/hosts 文件
    """
    remote_hosts_file = "/etc/hosts"
    temp_hosts_file_remote = "/tmp/hosts_temp_remote" # 远程临时文件

    try:
        # 下载当前的 /etc/hosts 文件到远程临时文件，而不是本地
        conn.run(f"cp {remote_hosts_file} {temp_hosts_file_remote}", hide=True)

        existing_hosts_content = conn.run(f"cat {temp_hosts_file_remote}", hide=True).stdout

        updated_hosts_lines = []
        # 保留原有的非空、非注释行
        for line in existing_hosts_content.splitlines():
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith('#'):
                parts = stripped_line.split()
                if len(parts) > 1:
                    # 检查是否是本次要添加的 IP-Hostname 对，如果是，则跳过，我们稍后重新添加
                    if parts[1] in hosts_map and parts[0] == hosts_map[parts[1]]:
                        continue
            updated_hosts_lines.append(line)
        
        # 追加或更新新的 IP-Hostname 对
        for hostname, ip in hosts_map.items():
            # 检查是否已存在精确的 IP-Hostname 对，避免重复添加
            if f"{ip} {hostname}" not in updated_hosts_lines:
                updated_hosts_lines.append(f"{ip} {hostname}")

        updated_hosts_content = "\n".join(updated_hosts_lines) + "\n" # 确保末尾有换行

        # 将更新后的内容上传回 /etc/hosts
        conn.put(StringIO(updated_hosts_content), remote=remote_hosts_file, sudo=True) # 需要sudo权限
        print(f"Configured /etc/hosts on {conn.host}")
    except Exception as e:
        print(f"Error configuring /etc/hosts on {conn.host}: {e}")
    finally:
        conn.run(f"rm -f {temp_hosts_file_remote}", hide=True, warn=True) # 清理远程临时文件

def setup_passwordless_ssh(hosts, initial_key_path, user="root", local_key_path="~/.ssh/cluster_key", remote_key_path="~/.ssh/cluster_key"):
    """
    设置多节点之间的SSH免密登录

    Args:
        hosts (list): 包含所有节点信息的字典列表，每个字典至少包含'hostname'和'ip'字段
        initial_key_path (str): 用于初始连接节点的私钥路径 (宿主机到远程节点)
        user (str): SSH用户名
        local_key_path (str): 本地生成的集群密钥路径
        remote_key_path (str): 远程节点上集群密钥的存储路径
    """
    # 确保每个节点信息包含 'ip' 字段
    for node in hosts:
        if 'ip' not in node:
            print(f"Error: Node {node['hostname']} is missing the 'ip' address. Please provide both hostname and IP.")
            return False

    # 在宿主机生成SSH密钥对 (这份密钥用于集群内部互相访问)
    print("=== Generating SSH key pair on local machine (for cluster inter-communication) ===")
    local_private_key_path, master_public_key_content = generate_ssh_key_locally(local_key_path)

    # 构建 hostname 到 IP 的映射，用于配置 /etc/hosts
    hosts_map = {node['hostname']: node['ip'] for node in hosts}

    # 分发和配置每个节点的 authorized_keys、私钥和 /etc/hosts
    print("\n=== Distributing and configuring SSH keys and /etc/hosts on all nodes ===")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for node in hosts:
            futures.append(executor.submit(
                lambda n: configure_node(n, initial_key_path, user, local_private_key_path, master_public_key_content, remote_key_path, hosts_map), n
            ))

        results = [f.result() for f in futures]

    if all(results):
        print("\n=== SSH passwordless setup completed successfully ===")
        return True
    else:
        print("\n=== SSH passwordless setup completed with errors. Please check logs. ===")
        return False

def configure_node(node, initial_key_path, user, local_private_key_path, master_public_key_content, remote_key_path, hosts_map):
    """
    配置单个节点，上传私钥和公钥，配置authorized_keys，配置/etc/hosts和SSH客户端
    """
    print(f"\n--- Configuring node: {node['hostname']} ({node['ip']}) ---")
    try:
        with Connection(
            host=node['hostname'],
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
        ) as conn:
            # 1. 创建 ~/.ssh 目录并设置权限
            conn.run("mkdir -p ~/.ssh", hide=True)
            conn.run("chmod 700 ~/.ssh", hide=True)

            # 2. 上传集群私钥到远程节点
            print(f"Uploading cluster private key to {node['hostname']}:{remote_key_path}...")
            upload_file(conn, local_private_key_path, remote_key_path)
            conn.run(f"chmod 600 {remote_key_path}", hide=True) # 设置私钥权限

            # 3. 将本地生成的集群公钥追加到远程节点的 authorized_keys
            print(f"Appending cluster public key to {node['hostname']}:~/.ssh/authorized_keys...")
            append_to_remote_file(conn, "~/.ssh/authorized_keys", master_public_key_content)

            # 4. (可选) 上传集群公钥文件本身到远程节点 (如果将来需要复制此.pub文件到其他地方)
            # 虽然内容已经追加到authorized_keys，但如果希望远程也保留一份独立的.pub文件，可以保留此行
            print(f"Uploading cluster public key file to {node['hostname']}:{remote_key_path}.pub...")
            upload_file(conn, f"{local_private_key_path}.pub", f"{remote_key_path}.pub")
            conn.run(f"chmod 644 {remote_key_path}.pub", hide=True) # 设置公钥文件权限

            # 5. 配置 /etc/hosts
            print(f"Configuring /etc/hosts on {node['hostname']}...")
            configure_hosts_file(conn, hosts_map)

            # 6. 配置 SSH 客户端选项 (特别是IdentityFile)
            print(f"Configuring SSH client settings on {node['hostname']}...")
            configure_ssh_config(conn, remote_key_path)

            print(f"Node {node['hostname']} configured successfully.")
            return True
    except Exception as e:
        print(f"Error configuring node {node['hostname']}: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Setup passwordless SSH between multiple nodes using a single key pair.')
    parser.add_argument('--hosts', required=True, nargs='+',
                       help='List of hostnames (e.g., node1 node2).')
    parser.add_argument('--ips', required=True, nargs='+',
                       help='List of IP addresses corresponding to the hostnames (e.g., 192.168.1.101 192.168.1.102).')
    parser.add_argument('--initial_key_path', required=True,
                       help='Path to the private key file on *local machine* used for initial SSH connection to remote nodes (e.g., ~/.ssh/id_rsa).')
    parser.add_argument('--user', default='root',
                       help='Username to connect as on remote nodes (default: root).')
    parser.add_argument('--local_cluster_key', default='~/.ssh/cluster_key',
                       help='Path to store the *generated cluster-wide* SSH key pair on local machine (default: ~/.ssh/cluster_key).')
    parser.add_argument('--remote_cluster_key', default='~/.ssh/cluster_key',
                       help='Path to store the *generated cluster-wide* SSH key pair on remote nodes (default: ~/.ssh/cluster_key).')

    args = parser.parse_args()

    if len(args.hosts) != len(args.ips):
        print("Error: The number of hostnames and IP addresses must be the same.")
        exit(1)

    # 准备包含 hostname 和 ip 的节点列表
    nodes = [{'hostname': host, 'ip': ip} for host, ip in zip(args.hosts, args.ips)]

    # 执行免密登录设置
    success = setup_passwordless_ssh(
        nodes,
        args.initial_key_path, # 用于初始连接的密钥
        args.user,
        args.local_cluster_key, # 本地生成的集群密钥路径
        args.remote_cluster_key # 远程存储的集群密钥路径
    )

    if success:
        print("\n=== Verification: Attempting SSH between cluster nodes ===")
        if len(nodes) < 2:
            print("Not enough nodes to perform inter-node SSH verification.")
        else:
            # 随机选择一个节点作为源节点，测试其到其他节点的连接
            source_node = nodes[0]
            # 确保 source_node 自己也能作为目标被测试
            test_target_nodes = nodes

            print(f"Attempting verification from local machine to {source_node['hostname']} ({source_node['ip']})...")
            try:
                # 初始连接到源节点，使用初始连接密钥
                with Connection(
                    host=source_node['hostname'],
                    user=args.user,
                    connect_kwargs={"key_filename": args.initial_key_path},
                ) as conn:
                    print(f"Successfully connected to {source_node['hostname']}. Now testing inter-node SSH from there.")
                    for target_node in test_target_nodes:
                        if source_node['hostname'] == target_node['hostname']:
                            # 测试自身到自身的免密登录（通过hostname）
                            print(f"  Testing SSH from {source_node['hostname']} to itself (via hostname)...")
                        else:
                            print(f"  Testing SSH from {source_node['hostname']} to {target_node['hostname']}...")

                        # 尝试从源节点SSH到目标节点，使用远程部署的集群密钥
                        try:
                            # 确保目标主机名可解析，且已经信任新的公钥
                            # -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null 在测试时跳过主机密钥检查，正式环境不推荐
                            # 这里需要使用在远程节点上配置的 cluster_key
                            remote_ssh_command = (
                                f"ssh -i {args.remote_cluster_key} "
                                f"-o StrictHostKeyChecking=no "
                                f"-o UserKnownHostsFile=/dev/null "
                                f"{target_node['hostname']} 'echo Success from $(hostname) to {target_node['hostname']}'"
                            )
                            result = conn.run(remote_ssh_command, hide=True)
                            print(f"    {source_node['hostname']} -> {target_node['hostname']}: {result.stdout.strip()}")
                        except Exception as test_e:
                            print(f"    {source_node['hostname']} -> {target_node['hostname']}: Test FAILED - {test_e}")
            except Exception as e:
                print(f"Verification failed: Could not establish initial connection to {source_node['hostname']}: {e}")
    else:
        print("Setup failed. Please review the error messages above.")