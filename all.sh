#!/bin/bash

# 此脚本将为以下 31 个任务类型创建 tmux 会话:
# kubernetes, streaming, catalyst, hive-thriftserver-1, hive-thriftserver-2, hive-thriftserver-3, hive-thriftserver-4, hive-thriftserver-5, sql-kafka-0-10, streaming-kafka-0-10, mesos, yarn, hadoop-cloud, connect, hive-1, hive-2, hive-3, sql-a-1, sql-a-2, sql-a-3, sql-a-4, sql-a-5, sql-a-6, sql-a-7, sql-b-1, sql-b-2, sql-c-1, sql-c-2, sql-c-3, sql-c-4, sql-c-5

# 定义任务类型数组
# TASK_TYPES=("catalyst" "connect" "hadoop-cloud" "kubernetes" "mesos" "streaming" "streaming-kafka-0-10" "yarn")
# TASK_TYPES=("hive-thriftserver-1" "hive-thriftserver-2" "hive-thriftserver-3" "hive-thriftserver-4" "hive-thriftserver-5" "sql-a-1" "sql-a-2" "sql-a-3" "sql-a-4" "sql-a-5" "sql-a-6" "sql-a-7" "sql-b-1" "sql-b-2" "sql-c-1" "sql-c-2" "sql-c-3" "sql-c-4" "sql-c-5")
# TASK_TYPES=("sql-kafka-0-10")
# TASK_TYPES=("hive-1" "hive-2" "hive-3" "hive-thriftserver-4" "sql-a-4" "sql-c-2")
# TASK_TYPES=("sql-a-6")
TASK_TYPES=("hive-3")
echo "=====================================================
准备启动 31 个 Spark 任务...
====================================================="

# 加载环境变量
if [ -f ".env" ]; then
    echo "正在加载环境变量: .env"
    source ".env"
else
    echo "警告: 环境变量文件 ~/.env 不存在!"
fi

# 循环处理每个任务类型
for TASK_TYPE in "${TASK_TYPES[@]}"; do
    # 创建会话名
    SESSION_NAME="$TASK_TYPE"
    
    # 检查会话是否已存在，如果存在则关闭
    tmux has-session -t $SESSION_NAME 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "会话 $SESSION_NAME 已存在，正在关闭..."
        tmux kill-session -t $SESSION_NAME
    fi
    
    # 创建新的 tmux 会话
    echo "创建会话 $SESSION_NAME"
    tmux new-session -d -s $SESSION_NAME
    
    # 发送命令以激活 conda 环境
    tmux send-keys -t $SESSION_NAME 'conda activate py10' C-m
    
    # 发送命令以运行任务
    PYTHON_CMD="python -m scheduler.tasks.task_spark_base2 --ak ${HW_SDK_AK} --sk ${HW_SDK_SK} --region ${HW_SDK_REGION} --vpc-id ${HW_SDK_VPCID} \\
        --security-group-id 6308b01a-0e7a-413a-96e2-07a3e507c324 \\
        --subnet-id 6a19704d-f0cf-4e10-a5df-4bd947b33ffc \\
        --ami 704106a0-5ab8-491c-8403-73041fca5f54 \\
        --num-instances 1 --timeout-hours 48 --instance-type kc1.2xlarge.4 --key-pair ${HW_SDK_KEYPEM} --run-number 1 --task-type $TASK_TYPE --actor zizdlp --use-ip"
    
    FULL_COMMAND="cd ~/schedule && $PYTHON_CMD"
    tmux send-keys -t $SESSION_NAME "$FULL_COMMAND" C-m
    
    echo "✅ 会话 $SESSION_NAME 已启动并正在运行任务: task_spark_base2 --task-type $TASK_TYPE"
    
    # 不是最后一个任务时，等待一段时间再启动下一个会话
    if [ ! "$TASK_TYPE" = "${TASK_TYPES[${#TASK_TYPES[@]}-1]}" ]; then
        echo "⏱️ 等待 5 秒后启动下一个会话..."
        sleep 5
    fi
done

echo "=====================================================
✅ 所有 31 个会话已启动完成
=====================================================
📋 使用以下命令查看会话列表:
   tmux list-sessions

🖥️ 使用以下命令连接到指定会话:
   tmux attach -t <任务类型>

❌ 使用以下命令关闭所有会话:
   for s in $(tmux list-sessions | cut -d: -f1); do tmux kill-session -t $s; done
"
