include .env
permission:
	chmod 400 ${HW_SDK_KEYPEM}.pem
createEIP:
	python hw/createEIP.py --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION}
createServerGroup:
	python hw/createInstance.py \
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
	python hw/fabricLogin.py --host ${MASTER} --key_path ${HW_SDK_KEYPEM}.pem --user root