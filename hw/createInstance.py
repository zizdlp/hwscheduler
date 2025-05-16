# coding: utf-8

import argparse
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkecs.v2 import *
from .createEIP import create_eip

def create_hw_instances(ak, sk, vpc_id, instance_index, region, instance_type, instance_zone, ami, key_pair, 
                       security_group_id, subnet_id, use_nvme, run_number, task_type, timeout_hours, 
                       actor, use_spot, use_ip):
    if use_ip.lower() == "true":
        origin_publicip = create_eip(ak, sk, region,task_type)
        print(f"申请公网IP:{origin_publicip.public_ip_address}")
    else:
        print("不使用公网ip")
    
    credentials = BasicCredentials(ak, sk)
    ecs_region = EcsRegion.value_of(region)
    
    client = EcsClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(ecs_region) \
        .build()
    
    try:
        request = CreatePostPaidServersRequest()
        rootVolumeServer = PostPaidServerRootVolume(
            volumetype="SSD"
        )
        nics = [
            PostPaidServerNic(subnet_id=subnet_id)
        ]
        security_groups = [
            PostPaidServerSecurityGroup(id=security_group_id)
        ]
        
        if use_ip.lower() == "true":
            bandwidth = PostPaidServerEipBandwidth(sharetype="PER", size=5)
            publicip = PostPaidServerPublicip(id=origin_publicip.id, delete_on_termination=True)
        
        user_data_script = '''#cloud-config
hostname: node{0}-{1}'''.format(instance_index,task_type)
        user_data = base64.b64encode(user_data_script.encode('utf-8')).decode('utf-8')
     
        server_tags = [
            PostPaidServerTag(key="Name", value=f'{run_number}-{task_type}'),
            PostPaidServerTag(key="Index", value=f'{instance_index}'),
            PostPaidServerTag(key="WarningHours", value=timeout_hours),
            PostPaidServerTag(key="Actor", value=actor)
        ]
        
        name = f"{run_number}-{task_type}-node{instance_index}-timeout{timeout_hours}-{actor}"
        serverbody = PostPaidServer(
            flavor_ref=instance_type,
            image_ref=ami,
            name=name,
            key_name=key_pair,
            vpcid=vpc_id,
            nics=nics,
            root_volume=rootVolumeServer,
            security_groups=security_groups,
            publicip=publicip if use_ip.lower() == "true" else None,
            user_data=user_data,
            server_tags=server_tags,
            availability_zone=instance_zone,
        )
        
        request.body = CreatePostPaidServersRequestBody(
            server=serverbody
        )
        
        response = client.create_post_paid_servers(request)
        
        if response.server_ids and len(response.server_ids) > 0:
            server_id = response.server_ids[0]
            print(f"实例创建成功！服务器ID: {server_id}")
            
            max_wait_time = 300
            wait_interval = 10
            elapsed_time = 0
            status = ""
            private_ip = None
            
            while elapsed_time < max_wait_time:
                try:
                    detail_request = ShowServerRequest(server_id=server_id)
                    detail_response = client.show_server(detail_request)
                    status = detail_response.server.status
                    print(f"当前实例状态: {status} (等待 {elapsed_time}/{max_wait_time}秒)")
                    
                    if status == "ACTIVE":
                        if hasattr(detail_response.server, 'addresses'):
                            addresses = detail_response.server.addresses
                            for network_name, ip_list in addresses.items():
                                for ip_info in ip_list:
                                    private_ip = ip_info.addr
                                    break
                                if private_ip:
                                    break

                        print(f"实例已成功启动！ID: {detail_response.server.id}, 私有IP: {private_ip}")
                        break
                    elif status == "ERROR":
                        print("实例创建失败！")
                        break
                except exceptions.ClientRequestException as e:
                    if e.error_code == "Ecs.0114":
                        print(f"实例尚未就绪... (等待 {elapsed_time}/{max_wait_time}秒)")
                    else:
                        raise e
                
                time.sleep(wait_interval)
                elapsed_time += wait_interval
            
            if elapsed_time >= max_wait_time:
                print(f"警告：等待超时（{max_wait_time}秒），实例最终状态: {status}")
            else:
                print(f"实例最终状态: {status}")
            
            return [instance_index, 
                    origin_publicip.public_ip_address if use_ip.lower() == "true" else private_ip, 
                    server_id, 
                    private_ip]
        else:
            print("警告：未返回服务器ID")
            return None
            
    except exceptions.ClientRequestException as e:
        print(e.status_code)
        print(e.request_id)
        print(e.error_code)
        print(e.error_msg)
        return None

def parallel_create_instances(ak, sk, vpc_id, num_instances, region, instance_type, instance_zone, ami, 
                            key_pair, security_group_id, subnet_id, use_nvme, run_number, task_type, 
                            timeout_hours, actor, use_spot, use_ip):
    instances = []
    with ThreadPoolExecutor(max_workers=num_instances) as executor:
        future_to_index = {
            executor.submit(
                create_hw_instances, ak, sk, vpc_id, instance_index, region, instance_type, 
                instance_zone, ami, key_pair, security_group_id, subnet_id, use_nvme, 
                run_number, task_type, timeout_hours, actor, use_spot, use_ip
            ): instance_index for instance_index in range(num_instances)
        }
        
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                instance = future.result()
                if instance:
                    instances.append(instance)
                    print(f'Instance {instance} launched as node{index}')
            except Exception as e:
                print(f'Error launching instance {index}: {e}')
    
    return instances

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Launch HW instances')
    
    # Required credentials
    parser.add_argument('--ak', required=True, help='Huawei Cloud Access Key')
    parser.add_argument('--sk', required=True, help='Huawei Cloud Secret Key')
    parser.add_argument('--vpc-id', required=True, help='VPC ID for the instances')
    
    # Instance configuration
    parser.add_argument('--num-instances', type=int, default=4, help='Number of instances to create')
    parser.add_argument('--region', type=str, default="ap-southeast-3", help='Region for the instances')
    parser.add_argument('--instance-type', type=str, default="kc1.large.4", help='Instance type')
    parser.add_argument('--instance-zone', type=str, default="ap-southeast-3a", help='Availability zone')
    parser.add_argument('--ami', type=str, default="04b5ea14-da35-47de-8467-66808dd62007", help='AMI ID')
    parser.add_argument('--key-pair', type=str, required=True, help='SSH key pair name')
    parser.add_argument('--security-group-id', type=str, 
                       default="6308b01a-0e7a-413a-96e2-07a3e507c324", help='Security group ID')
    parser.add_argument('--subnet-id', type=str, 
                       default="6a19704d-f0cf-4e10-a5df-4bd947b33ffc", help='Subnet ID')
    
    # Optional parameters
    parser.add_argument('--use-nvme', type=bool, default=True, help='Whether to use NVMe')
    parser.add_argument('--run-number', type=str, default="0", help='Run number identifier')
    parser.add_argument('--task-type', type=str, default="spark", help='Task type identifier')
    parser.add_argument('--timeout-hours', type=str, default="6", help='Timeout in hours')
    parser.add_argument('--actor', type=str, help='User who triggered the creation')
    parser.add_argument('--use-spot', type=str, default="true", help='Whether to use spot instances')
    parser.add_argument('--use-ip', type=str, default="true", help='Whether to assign public IP')
    
    args = parser.parse_args()
    
    instances = parallel_create_instances(
        ak=args.ak,
        sk=args.sk,
        vpc_id=args.vpc_id,
        num_instances=args.num_instances,
        region=args.region,
        instance_type=args.instance_type,
        instance_zone=args.instance_zone,
        ami=args.ami,
        key_pair=args.key_pair,
        security_group_id=args.security_group_id,
        subnet_id=args.subnet_id,
        use_nvme=args.use_nvme,
        run_number=args.run_number,
        task_type=args.task_type,
        timeout_hours=args.timeout_hours,
        actor=args.actor,
        use_spot=args.use_spot,
        use_ip=args.use_ip
    )
    
    print("Created instances:", instances)