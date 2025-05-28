# coding: utf-8

import time
import argparse  # Import argparse
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkecs.v2 import *

def delete_servers(servers, region, ak, sk, max_retries=2):
    """
    Deletes Huawei Cloud ECS instances.

    Args:
        servers (list): A list of ServerId objects to delete.
        region (str): Huawei Cloud Region.
        ak (str): Huawei Cloud Access Key.
        sk (str): Huawei Cloud Secret Key.
        max_retries (int): Maximum number of retries.

    Returns:
        bool: True if all servers were deleted successfully, False otherwise.
    """
    print(f"准备删除服务器: {servers}")

    try:
        credentials = BasicCredentials(ak, sk)
        ecs_region = EcsRegion.value_of(region)

        client = EcsClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(ecs_region) \
            .build()

        retry_count = 0
        last_exception = None

        while retry_count <= max_retries:
            try:
                # 1. 发起删除请求（同时删除EIP和磁盘）
                request = DeleteServersRequest()
                request.body = DeleteServersRequestBody(
                    servers=servers,
                    delete_publicip=True,  # 同时删除EIP
                    delete_volume=True     # 同时删除磁盘
                )
                response = client.delete_servers(request)

                # 2. 获取Job ID
                job_id = response.job_id
                print(f"删除操作已提交，Job ID: {job_id}")

                # 3. 轮询Job状态
                max_attempts = 30  # 最大尝试次数
                wait_interval = 10  # 每次等待间隔(秒)

                from huaweicloudsdkecs.v2 import ShowJobRequest

                for attempt in range(max_attempts):
                    job_request = ShowJobRequest(job_id=job_id)
                    job_response = client.show_job(job_request)

                    status = job_response.status
                    print(f"Job状态检查 [{attempt+1}/{max_attempts}]: {status}")

                    # 添加子任务状态检查
                    if hasattr(job_response, 'sub_jobs') and job_response.sub_jobs:
                        for sub_job in job_response.sub_jobs:
                            if sub_job.status == "FAIL":
                                print(f"子任务失败 - 类型: {sub_job.type}, 原因: {sub_job.fail_reason}")

                    if status == "SUCCESS":
                        print("服务器及相关资源(EIP、磁盘)删除成功完成!")
                        return True
                    elif status == "FAIL":
                        print(f"删除失败! 错误信息: {job_response.fail_reason}")
                        # 准备重试
                        break

                    time.sleep(wait_interval)

                print(f"等待超时，未能在预期时间内完成删除操作。最后状态: {status}")

                # 如果执行到这里，说明删除失败或超时
                if retry_count < max_retries:
                    retry_count += 1
                    print(f"删除失败，准备第 {retry_count} 次重试...")
                    time.sleep(5)  # 等待5秒再重试
                    continue
                else:
                    return False

            except exceptions.ClientRequestException as e:
                print(f"操作失败: {e.error_msg} (错误码: {e.error_code})")
                last_exception = e
                if retry_count < max_retries:
                    retry_count += 1
                    print(f"出现异常，准备第 {retry_count} 次重试...")
                    time.sleep(5)  # 等待5秒再重试
                    continue
                else:
                    return False

        print(f"已达到最大重试次数 {max_retries}，删除操作最终失败")
        if last_exception:
            print(f"最后错误信息: {last_exception.error_msg}")
        return False

    except ValueError:
        print(f"Invalid region: {region}.  Please check the available EcsRegion values.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during client setup: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Delete Huawei Cloud ECS Instances')
    parser.add_argument('--server-ids', nargs='+', required=True, help='List of server IDs to delete')
    parser.add_argument('--region', required=True, help='Huawei Cloud Region')
    parser.add_argument('--ak', required=True, help='Huawei Cloud Access Key')
    parser.add_argument('--sk', required=True, help='Huawei Cloud Secret Key')

    args = parser.parse_args()

    # Convert server IDs to ServerId objects
    server_ids = [ServerId(id=server_id) for server_id in args.server_ids]

    success = delete_servers(server_ids, args.region, args.ak, args.sk)

    if success:
        print("All servers deleted successfully.")
    else:
        print("One or more servers failed to delete.")