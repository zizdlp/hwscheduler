from fabric import Connection
import argparse
import requests

def start_github_runner(node, ssh_key_path, user, github_token, runner_name):
    """
    简化版 GitHub Actions Runner 启动脚本
    1. 获取 registration token
    2. 以 ubuntu 用户在已有的 /home/ubuntu/actions-runner 目录中执行 config.sh
    3. 安装并启动服务
    """
    try:
        with Connection(
            host=node,
            user=user,  # 外部连接使用 root 用户
            connect_kwargs={"key_filename": ssh_key_path},
        ) as conn:
            # 1. 从 GitHub API 获取 registration token
            print("获取 GitHub runner 注册 token...")
            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            response = requests.post(
                "https://api.github.com/repos/chukonu-team/chukonu/actions/runners/registration-token",
                headers=headers
            )
            response.raise_for_status()
            registration_token = response.json()["token"]
            
            # 2. 以 ubuntu 用户身份执行 config.sh
            print("以 ubuntu 用户配置 GitHub Actions runner...")
            
            # 确保目录权限正确
            conn.run("chown -R ubuntu:ubuntu /home/ubuntu/actions-runner", warn=True)
            
            # 使用 sudo -u ubuntu 执行命令
            config_cmd = (
                f"cd /home/ubuntu/actions-runner && "
                f"./config.sh --url https://github.com/chukonu-team/chukonu "
                f"--token {registration_token} --name {runner_name} --unattended"
            )
            
            result = conn.run(f"sudo -u ubuntu bash -c '{config_cmd}'", warn=True)
            
            if result.failed:
                print(f"Runner 配置失败: {result.stderr}")
                return False
            
            print("GitHub Actions runner 配置成功!")
            
            # 3. 安装并启动服务
            print("安装并启动 GitHub Actions runner 服务...")
            
            # 安装服务
            install_result = conn.run(
                "sudo -u ubuntu bash -c 'cd /home/ubuntu/actions-runner && echo '123456' | sudo -S ./svc.sh install'",
                warn=True
            )
            
            if install_result.failed:
                print(f"服务安装失败: {install_result.stderr}")
                return False
                
            # 启动服务
            start_result = conn.run(
                "sudo -u ubuntu bash -c 'cd /home/ubuntu/actions-runner && echo '123456' | sudo -S ./svc.sh start'",
                warn=True
            )
            
            if start_result.failed:
                print(f"服务启动失败: {start_result.stderr}")
                return False
                
            print("GitHub Actions runner 服务已成功安装并启动!")
            return True
            
    except Exception as e:
        print(f"在节点 {node} 上启动 GitHub runner 时出错: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='启动 GitHub Actions runner (简化版)')
    parser.add_argument('--node', required=True, help='远程节点主机名或IP')
    parser.add_argument('--key_path', required=True, help='SSH私钥路径')
    parser.add_argument('--user', default="root", help='远程用户 (默认: root)')
    parser.add_argument('--github_token', required=True, help='GitHub 个人访问令牌')
    parser.add_argument('--runner_name', required=True, help='Runner名称')
    args = parser.parse_args()
    
    success = start_github_runner(
        args.node, 
        args.key_path, 
        args.user, 
        args.github_token, 
        args.runner_name
    )
    
    if not success:
        exit(1)