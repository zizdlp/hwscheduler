from fabric import Connection
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import argparse

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

def read_cluster_info_file(file_path):
    """
    读取集群信息文件，并将其转换为字典列表。
    每行格式：hostname public_ip server_id private_ip
    """
    nodes_info = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 4:
                    node = {
                        'hostname': parts[0],
                        'public_ip': parts[1],
                        'server_id': parts[2],
                        'private_ip': parts[3]
                    }
                    nodes_info.append(node)
                elif len(parts) > 0: # 忽略空行
                    print(f"Warning: Skipping malformed line in {file_path}: '{line.strip()}' (expected 4 parts)")
    except FileNotFoundError:
        print(f"Error: Cluster info file not found at '{file_path}'")
        return []
    except Exception as e:
        print(f"Error reading cluster info file: {e}")
        return []
    return nodes_info

def clean_and_update_hosts(conn, nodes):
    """
    清理并更新/etc/hosts文件
    1. 删除所有包含节点hostname的行
    2. 添加所有节点的private_ip和hostname映射
    """
    # 1. 获取当前hosts内容
    result = conn.run("cat /etc/hosts", hide=True)
    original_lines = result.stdout.splitlines()
    
    # 2. 过滤掉包含任何节点hostname的行
    node_hostnames = [node['hostname'] for node in nodes]
    preserved_lines = []
    for line in original_lines:
        # 保留不以节点hostname结尾的行 (排除注释和空白行)
        if not any(line.strip().endswith(hostname) for hostname in node_hostnames) \
           and not line.strip().startswith('#') \
           and line.strip() != '':
            preserved_lines.append(line)
    
    # 3. 添加所有节点的映射
    new_entries = []
    for node in nodes:
        new_entries.append(f"{node['private_ip']}\t{node['hostname']}")
    
    # 4. 组合内容并写回
    new_hosts_content = '\n'.join(preserved_lines + new_entries)
    
    # 使用sudo更新hosts文件
    conn.sudo(f"echo '{new_hosts_content}' > /etc/hosts", warn=True)
    
    # 验证更新
    conn.run("cat /etc/hosts")

def configure_node(node, initial_key_path, user, nodes, private_key):
    """
    配置单个节点，上传私钥和公钥，配置authorized_keys，配置/etc/hosts和SSH客户端
    """
    print(f"\n--- Configuring node: {node['hostname']} ({node['public_ip']}) ---")
    try:
        with Connection(
            host=node['public_ip'],  # 使用public_ip连接
            user=user,
            connect_kwargs={"key_filename": initial_key_path},
        ) as conn:
            # 1. 清理并更新hosts文件
            print("\nUpdating /etc/hosts...")
            clean_and_update_hosts(conn, nodes)
            
            # 2. 上传私有钥匙，追加公钥到authorized_keys
            print("\nConfiguring SSH keys...")
            
            # 确保.ssh目录存在且权限正确
            conn.run("mkdir -p ~/.ssh && chmod 700 ~/.ssh")
            
            # 更可靠的文件上传方式
            # 上传私钥
            with open(private_key, 'rb') as f:
                conn.put(f, remote="/tmp/id_rsa_temp")
            conn.run("mv /tmp/id_rsa_temp ~/.ssh/id_rsa && chmod 600 ~/.ssh/id_rsa")
            
            # 上传公钥
            with open(f"{private_key}.pub", 'rb') as f:
                conn.put(f, remote="/tmp/id_rsa_temp.pub")
            conn.run("mv /tmp/id_rsa_temp.pub ~/.ssh/id_rsa.pub && chmod 644 ~/.ssh/id_rsa.pub")
            
            # 将公钥添加到authorized_keys
            conn.run(f"cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys")
            conn.run("chmod 600 ~/.ssh/authorized_keys")
            
            # 配置SSH客户端
            ssh_config = """
Host *
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
"""
            # 使用更可靠的方式上传SSH配置
            conn.run("echo '{}' > /tmp/ssh_config_temp".format(ssh_config.replace("'", "'\\''")))
            conn.run("mv /tmp/ssh_config_temp ~/.ssh/config && chmod 600 ~/.ssh/config")
            
            print(f"SSH configuration completed for {node['hostname']}")
            return True
    except Exception as e:
        print(f"Error configuring node {node['hostname']}: {e}")
        return False

def configure_pwdless(cluster_info,key_path,user):
    local_key_path = "/root/.ssh/cluster_key"
    nodes = read_cluster_info_file(cluster_info)
    
    if not nodes:
        print("No nodes found in cluster info file. Exiting.")
        exit(1)
    
    print(f"Found {len(nodes)} nodes in cluster:")
    for node in nodes:
        print(f"  {node['hostname']} (Public IP: {node['public_ip']}, Private IP: {node['private_ip']})")
    
    # 在宿主机生成SSH密钥对
    print("=== Generating SSH key pair on local machine ===")
    local_private_key_path, public_key_content = generate_ssh_key_locally(local_key_path)
    
    
    
    with ThreadPoolExecutor(max_workers=len(nodes)) as executor:
        futures = []
        for node in nodes:
            futures.append(executor.submit(
                configure_node, node, key_path, user, nodes,local_private_key_path
            ))
        
        # Wait for all tasks to complete and collect results
        results = [f.result() for f in futures]
        
        # Print summary
        successful = sum(1 for r in results if r)
        print(f"\nConfiguration completed: {successful} successful, {len(results)-successful} failed")
        
        if successful < len(results):
            print("Failed nodes:")
            for i, result in enumerate(results):
                if not result:
                    print(f"  {nodes[i]['hostname']}")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='配置集群免密登陆')
    parser.add_argument('--cluster-info', required=True, help='集群配置信息文件路径')
    parser.add_argument('--key-path', required=True, help='登陆集群密钥文件路径')
    parser.add_argument('--user', default='root', help='The username to connect as (default: root).')
    args = parser.parse_args()
    configure_pwdless(args.cluster_info,args.key_path,args.user)
    