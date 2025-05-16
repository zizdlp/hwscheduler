def save_info(instances,task_type):
    fileName= task_type+"_nodes_info.txt"
    # 保存节点信息到一个文件，包含 Public IP 地址
    with open(f'./cache/{fileName}', 'w') as f:
        for instance in instances:
            # 保存节点信息到文件，每一行格式为：node{index} {Public IP} {server_id} {private_ip}
            f.write(f'node{instance[0]} {instance[1]} {instance[2]} {instance[3]}\n')

    print(f'Node information with Public IPs has been saved to {fileName}')

