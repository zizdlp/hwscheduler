# coding: utf-8

import argparse
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkeip.v2.region.eip_region import EipRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkeip.v2 import *

def create_eip(ak, sk, region, task_name):
    credentials = BasicCredentials(ak, sk)
    eip_region = EipRegion.value_of(region)
    
    client = EipClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(eip_region) \
        .build()

    try:
        request = CreatePublicipRequest()
        publicip = CreatePublicipOption(
            type="5_bgp"
        )
        bandwidth = CreatePublicipBandwidthOption(share_type="PER", name=task_name, size=5)
        request.body = CreatePublicipRequestBody(
            bandwidth=bandwidth,
            publicip=publicip,
        )
        response = client.create_publicip(request)
        if(response.publicip):
            pub = response.publicip
            print("Created EIP ID:", pub.id)
            print("EIP Address:", pub.public_ip_address)
            
            # Write to file
            filename = f"./cache/{task_name}_ip_info.txt"
            with open(filename, 'w') as f:
                f.write(f"{pub.id}\t{pub.public_ip_address}\n")
            
            print(f"EIP information written to {filename}")
            
        return response.publicip

    except exceptions.ClientRequestException as e:
        print(e.status_code)
        print(e.request_id)
        print(e.error_code)
        print(e.error_msg)
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create Huawei Cloud EIP')
    parser.add_argument('--ak', required=True, help='Huawei Cloud Access Key')
    parser.add_argument('--sk', required=True, help='Huawei Cloud Secret Key')
    parser.add_argument('--region', required=True, help='Huawei Cloud Region')
    parser.add_argument('--task', required=True, help='Task Name')
    
    args = parser.parse_args()
    
    pub = create_eip(args.ak, args.sk, args.region, args.task)
