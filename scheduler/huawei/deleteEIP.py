# coding: utf-8

import argparse
import os
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkeip.v2.region.eip_region import EipRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkeip.v2 import *

def delete_eip(ak, sk, region, publicip_id):
    credentials = BasicCredentials(ak, sk)
    eip_region = EipRegion.value_of(region)
    
    client = EipClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(eip_region) \
        .build()

    try:
        request = DeletePublicipRequest(publicip_id=publicip_id)
        response = client.delete_publicip(request)
        return response

    except exceptions.ClientRequestException as e:
        print(e.status_code)
        print(e.request_id)
        print(e.error_code)
        print(e.error_msg)
        return None

def delete_eip_bytask(ak, sk, region, info_path):
    # Check if file exists
    if not os.path.exists(info_path):
        print(f"Error: File {info_path} not found")
        return False
    
    # Read EIP information from file
    try:
        with open(info_path, 'r') as f:
            lines = f.readlines()
            
            # Skip header if exists
            if lines[0].strip().lower() in ['id,ip', 'id\tip']:
                lines = lines[1:]
                
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Handle both tab and comma separated files
                if '\t' in line:
                    eip_id, eip_address = line.split('\t')[:2]
                elif ',' in line:
                    eip_id, eip_address = line.split(',')[:2]
                else:
                    eip_id = line  # If only ID is present
                    
                eip_id = eip_id.strip()
                print(f"Deleting EIP ID: {eip_id}")
                
                # Delete the EIP
                result = delete_eip(ak, sk, region, eip_id)
                if result:
                    print(f"Successfully deleted EIP: {eip_id}")
                else:
                    print(f"Failed to delete EIP: {eip_id}")
        return True
        
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Delete Huawei Cloud EIP')
    parser.add_argument('--ak', required=True, help='Huawei Cloud Access Key')
    parser.add_argument('--sk', required=True, help='Huawei Cloud Secret Key')
    parser.add_argument('--region', required=True, help='Huawei Cloud Region')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ip-id', help='public ip id')
    group.add_argument('--info-path', help='path to file containing EIP info')
    
    args = parser.parse_args()
    
    if args.ip_id:
        # Delete single EIP
        result = delete_eip(args.ak, args.sk, args.region, args.ip_id)
        if result:
            print(f"Successfully deleted EIP ID: {args.ip_id}")
    else:
        # Delete EIPs from file
        success = delete_eip_bytask(args.ak, args.sk, args.region, args.info_path)
        if success:
            print("All EIPs from file processed")