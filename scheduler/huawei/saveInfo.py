import re
import subprocess
import os
import time
import socket
def is_root():
    """检查当前用户是否是root用户"""
    return os.geteuid() == 0

def cleanHostsBeforeInsert(task_type):
    """
    清理 /etc/hosts 中所有 node{数字}_{task_type} 的条目
    """
    hosts_file = '/etc/hosts'
    pattern = re.compile(r'\b(node\d+-{})\b'.format(re.escape(task_type)))  # 匹配 node 后跟数字和指定任务类型的单词
    
    print("\n=== Before modification ===")
    printFile(hosts_file)
    
    try:
        # 读取原始内容
        with open(hosts_file, 'r') as f:
            original_lines = f.readlines()
        
        # 过滤掉所有 node{数字}_{task_type} 的行
        new_lines = [line for line in original_lines if not pattern.search(line)]
        
        # 如果内容没有变化则直接返回
        if original_lines == new_lines:
            print("\nNo node entries found to remove")
            return
        
        # 构建新内容字符串
        new_content = ''.join(new_lines)
        
        # 根据用户权限决定是否使用sudo
        cmd = ['tee', hosts_file]
        if not is_root():
            cmd.insert(0, 'sudo')
        
        # 使用 tee 覆盖写入文件
        process = subprocess.Popen(
            cmd,  # 注意这里没有 -a 参数，表示覆盖写入
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        stdout, stderr = process.communicate(input=new_content)
        
        if process.returncode == 0:
            print("\n=== After modification ===")
            printFile(hosts_file)
            print("\nSuccessfully cleaned node entries from /etc/hosts")
        else:
            print(f"\nError cleaning /etc/hosts: {stderr.strip()}")
            
    except Exception as e:
        print(f"\nError processing /etc/hosts: {str(e)}")
def printFile(path):
    try:
        # 根据用户权限决定是否使用sudo
        cmd = ['cat', path]
        if not is_root():
            cmd.insert(0, 'sudo')
            
        # 使用 subprocess 调用 cat
        result = subprocess.run(cmd, 
                               capture_output=True, 
                               text=True)
        if result.returncode == 0:
            print(f"=== {path} content ===")
            print(result.stdout)
        else:
            print(f"Error reading {path}: {result.stderr}")
    except Exception as e:
        print(f"Error: {e}")
    
# 使用 ssh-keyscan 将节点主机名添加到 known_hosts
def add_to_known_hosts(hostname, retries=20, delay=5):
    ssh_dir = os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    
    # 确保 known_hosts 文件存在且权限正确
    known_hosts_path = os.path.join(ssh_dir, "known_hosts")
    if not os.path.exists(known_hosts_path):
        open(known_hosts_path, 'a').close()
    os.chmod(known_hosts_path, 0o600)
    
    for attempt in range(retries):
        try:
            # 先检查主机名是否能解析（避免直接调用 ssh-keyscan 失败）
            try:
                socket.gethostbyname(hostname)
            except socket.gaierror:
                print(f"DNS resolution failed for {hostname}, retrying...")
                time.sleep(delay)
                continue
            
            # 执行 ssh-keyscan 并验证输出
            result = subprocess.run(
                f'ssh-keyscan -H {hostname}',
                shell=True,
                check=True,
                capture_output=True,
                text=True
            )
            
            if not result.stdout.strip():
                raise subprocess.CalledProcessError(1, 'ssh-keyscan', "Empty output")
            
            # 追加到 known_hosts
            with open(known_hosts_path, 'a') as f:
                f.write(result.stdout)
            
            print(f'Successfully added {hostname} to known_hosts.')
            return
            
        except (subprocess.CalledProcessError, socket.gaierror) as e:
            print(f'Attempt {attempt + 1}/{retries} failed: {str(e)}')
            if attempt < retries - 1:
                time.sleep(delay)
    
    print(f'Failed to add {hostname} to known_hosts after {retries} attempts.')
    raise RuntimeError("Max retries exceeded")

def save_info(instances,task_type,is_public):
    fileName = task_type + "_nodes_info.txt"
    # 保存节点信息到一个文件，包含 Public IP 地址
    with open(f'./cache/{fileName}', 'w') as f:
        for instance in instances:
            # 保存节点信息到文件，每一行格式为：node{index} {Public IP} {server_id} {private_ip}
            f.write(f'node{instance[0]}-{task_type} {instance[1]} {instance[2]} {instance[3]}\n')
            
            # 根据是否 root 决定是否添加 sudo
            sudo_prefix = "" if is_root() else "sudo "
            ip = instance[1] if is_public else instance[3]
            command = f"echo '{ip} node{instance[0]}-{task_type}' | {sudo_prefix}tee -a /etc/hosts"
            # 执行命令
            subprocess.run(command, shell=True, check=True)
            add_to_known_hosts(f"node{instance[0]}-{task_type}")
            
    print(f'Node information with Public IPs has been saved to {fileName}')
    
    