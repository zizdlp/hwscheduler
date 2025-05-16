def save_info(instances):
    # 保存节点信息到一个文件，包含 Public IP 地址
    with open('./.github/scripts/nodes_info.txt', 'w') as f:
        for instance in instances:
            # 保存节点信息到文件，每一行格式为：node{index} {Public IP} {server_id} {private_ip}
            f.write(f'node{instance[0]} {instance[1]} {instance[2]} {instance[3]}\n')

    print('Node information with Public IPs has been saved to ./.github/scripts/nodes_info.txt')

