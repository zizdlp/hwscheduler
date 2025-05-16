# coding: utf-8
import sys
sys.path.append("/mnt/schedule")  # Add the project root to the path
from hw.createEIP import create_eip
from hw.saveInfo import save_info
from hw.createInstance import parallel_create_instances

import argparse
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkecs.v2 import *
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='DEMO')
    
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
    save_info(instances,task_type=args.task_type)