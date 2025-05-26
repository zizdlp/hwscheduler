#!/bin/bash

# 加载环境变量
set -a  # 自动导出所有变量
source .env
set +a

# Define your task types with proper quoting
task_types=(
    "hive-thriftserver-1"
    "hive-thriftserver-2"
)

# Initialize Conda properly
CONDA_SETUP='
export PATH="/root/miniconda3/bin:$PATH"
. /root/miniconda3/etc/profile.d/conda.sh
conda activate py10
'

for task_type in "${task_types[@]}"; do
    echo "Starting task: ${task_type}"
    session_name="task_${task_type//[^a-zA-Z0-9]/_}"
    
    # Create tmux session with full environment setup
    tmux new-session -d -s "$session_name" \
        "bash -c \"
        set -a
        source .env
        set +a
        export PATH=\\\"/root/miniconda3/bin:\\\$PATH\\\"
        source /root/miniconda3/etc/profile.d/conda.sh
        conda activate py10
        cd ~/schedule
        python -m scheduler.tasks.task_spark_base2 \\
            --ak \\\${HW_SDK_AK} \\
            --sk \\\${HW_SDK_SK} \\
            --region \\\${HW_SDK_REGION} \\
            --vpc-id \\\${HW_SDK_VPCID} \\
            --security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \\
            --subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \\
            --ami 704106a0-5ab8-491c-8403-73041fca5f54 \\
            --num-instances 1 \\
            --instance-type kc1.2xlarge.4 \\
            --key-pair \\\${HW_SDK_KEYPEM} \\
            --run-number 1 \\
            --task-type ${task_type} \\
            --actor zizdlp \\
            2>&1 | tee /tmp/${session_name}.log
        exec sleep infinity  # Keep window open
        \""
done

# Verification
sleep 2
echo -e "\nActive tmux sessions:"
tmux list-sessions
echo -e "\nProcesses:"
ps aux | grep -E 'python|task_spark_base2|tmux'