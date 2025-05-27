include .env
permission:
	chmod 400 ${HW_SDK_KEYPEM}.pem
createEIP:
	python3 hw/createEIP.py --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --task "alice-to"
createServerGroup:
	python3 hw/createInstance.py \
	 	--ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} \
		--vpc-id ${HW_SDK_VPCID} \
		--num-instances 4 \
		--instance-type kc1.large.4 \
		--instance-zone ap-southeast-3a \
		--ami 04b5ea14-da35-47de-8467-66808dd62007 \
		--key-pair ${HW_SDK_KEYPEM} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--actor alice \
		--use-ip true
deleteServerGroup:
	python hw/deleteServer.py \
	 	--ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} \
		--server-ids "9c9003e3-97c5-4ac8-9141-e4c9d6c96dae"
test_login:
	python -m scheduler.huawei.fabric_login --host ${MASTER} --key_path ${HW_SDK_KEYPEM}.pem --user root
start_container:
	docker run -itd --name temp_schedule -v ./:/mnt/schedule ubuntu:22.04 /bin/bash
use_container:
	docker exec -it temp_schedule /bin/bash
delete_container:
	docker stop temp_schedule
	docker rm temp_schedule
line:
	python3 tasks/line.py \
	 	--ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} \
		--vpc-id ${HW_SDK_VPCID} \
		--num-instances 4 \
		--instance-type kc1.large.4 \
		--instance-zone ap-southeast-3a \
		--ami 04b5ea14-da35-47de-8467-66808dd62007 \
		--task-type "welldone" \
		--key-pair ${HW_SDK_KEYPEM} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--actor alice \
		--use-ip true 
task_build_chukonu:
	python -m scheduler.tasks.task_build_chukonu \
	 	--ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} \
		--vpc-id ${HW_SDK_VPCID} \
		--num-instances 1 \
		--instance-type kc1.large.4 \
		--instance-zone ap-southeast-3a \
		--ami 27164e55-d72c-4611-8c74-3e4227197cae \
		--task-type "build-chukonu-asb" \
		--key-pair ${HW_SDK_KEYPEM} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--actor zizdlp \
		--use-ip true 
task_start_runner:
	python -m scheduler.tasks.task_start_runner \
	 	--ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} \
		--vpc-id ${HW_SDK_VPCID} \
		--num-instances 1 \
		--instance-type kc1.large.4 \
		--instance-zone ap-southeast-3a \
		--ami c3e36999-70ef-48ca-8235-81ca7ca65ef8 \
		--task-type "start-runner" \
		--key-pair ${HW_SDK_KEYPEM} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--actor zizdlp \
		--use-ip true \
		--github-token ${GITHUB_TOKEN} \
		--run-number 6 \
		--user root 
task_spark_base:
	python scheduler/tasks/task_spark_base.py \
	 	--ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} \
		--vpc-id ${HW_SDK_VPCID} \
		--num-instances 1 \
		--instance-type kc1.xlarge.4 \
		--instance-zone ap-southeast-3a \
		--ami 704106a0-5ab8-491c-8403-73041fca5f54 \
		--task-type "test-spark-base-kubernetes" \
		--key-pair ${HW_SDK_KEYPEM} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--actor zizdlp \
		--use-ip true \
		--task-name kubernetes
login:
	ssh -i ${HW_SDK_KEYPEM}.pem  root@node0-test-spark-base-kubernetes
pwd_less:
	python3 hw/config_pwdless.py --cluster-info "./cache/spark_nodes_info.txt"  --key_path ${HW_SDK_KEYPEM}.pem

login_a:
	ssh -i ${HW_SDK_KEYPEM}.pem  root@101.44.161.156

delete_server:
	python3 hw/deleteServer.py
test_chukonu:
	python3 hw/test_build_chukonu.py --node node0-build-chukonu  --key_path ${HW_SDK_KEYPEM}.pem
delete_ip:
	python3 hw/deleteEIP.py  --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --ip-id 0153127f-9a12-4a4d-9259-753bc28c6241
delete_ip_task:
	python3 hw/deleteEIP.py  --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --info-path ./cache/alice-to_ip_info.txt
test_eip_manager:
	python -m scheduler.huawei.eip_manager  --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --task alice --num 4 --auto-clean 
test_ecs_manager:
	python -m scheduler.huawei.ecs_manager  --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --vpc-id ${HW_SDK_VPCID} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--num-instances 4 --instance-type kc1.large.4 --key-pair ${HW_SDK_KEYPEM} --run-number 1001 --task-type spark --actor admin --use-ip
task_build_chukonu2:
	python -m scheduler.tasks.task_build_chukonu2  --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --vpc-id ${HW_SDK_VPCID} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--ami 27164e55-d72c-4611-8c74-3e4227197cae \
		--num-instances 1 --instance-type kc1.large.4 --key-pair ${HW_SDK_KEYPEM} --run-number 1 --task-type build-chukonu --actor zizdlp --use-ip
task_spark_base2:
	python -m scheduler.tasks.task_spark_base2  --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --vpc-id ${HW_SDK_VPCID} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--ami 704106a0-5ab8-491c-8403-73041fca5f54 \
		--num-instances 1 --instance-type kc1.xlarge.4 --key-pair ${HW_SDK_KEYPEM} --run-number 1 --task-type yarn --actor zizdlp --use-ip
build_wheel:
	python -m build

test_abc:
	tmux new-session -d -s yarn
	tmux send-keys -t yarn 'conda activate py10' C-m
	tmux send-keys -t yarn 'cd ~/schedule && make task_spark_base2' C-m
	tmux attach-session -t yarn

task_spark_UT:
	python -m scheduler.tasks.task_spark_base2  --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --vpc-id ${HW_SDK_VPCID} \
		--security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \
		--subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \
		--ami 704106a0-5ab8-491c-8403-73041fca5f54 \
		--num-instances 1 --instance-type kc1.xlarge.4 --key-pair ${HW_SDK_KEYPEM} --run-number 1 --task-type yarn --actor zizdlp --use-ip