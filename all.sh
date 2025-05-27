#!/bin/bash

# 此脚本将为以下 31 个任务类型创建 tmux 会话:
# kubernetes, streaming, catalyst, hive-thriftserver-1, hive-thriftserver-2, hive-thriftserver-3, hive-thriftserver-4, hive-thriftserver-5, sql-kafka-0-10, streaming-kafka-0-10, mesos, yarn, hadoop-cloud, connect, hive-1, hive-2, hive-3, sql-a-1, sql-a-2, sql-a-3, sql-a-4, sql-a-5, sql-a-6, sql-a-7, sql-b-1, sql-b-2, sql-c-1, sql-c-2, sql-c-3, sql-c-4, sql-c-5

# 定义任务类型数组
TASK_TYPES=("kubernetes" "streaming" "catalyst" "hive-thriftserver-1" "hive-thriftserver-2" "hive-thriftserver-3" "hive-thriftserver-4" "hive-thriftserver-5" "sql-kafka-0-10" "streaming-kafka-0-10" "mesos" "yarn" "hadoop-cloud" "connect" "hive-1" "hive-2" "hive-3" "sql-a-1" "sql-a-2" "sql-a-3" "sql-a-4" "sql-a-5" "sql-a-6" "sql-a-7" "sql-b-1" "sql-b-2" "sql-c-1" "sql-c-2" "sql-c-3" "sql-c-4" "sql-c-5")

echo "=====================================================
准备启动 31 个 Spark 任务...
====================================================="

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
    FULL_COMMAND="cd ~/schedule && make task_spark_base2_$TASK_TYPE"
    tmux send-keys -t $SESSION_NAME "$FULL_COMMAND" C-m
    
    echo "✅ 会话 $SESSION_NAME 已启动并正在运行任务: $FULL_COMMAND"
    
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
