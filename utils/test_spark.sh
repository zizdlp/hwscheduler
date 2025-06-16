#!/bin/bash

# 清空环境变量
unset SPARK_HOME
unset HADOOP_COMMON_HOME
unset HADOOP_COMMON_LIB_NATIVE_DIR
unset HADOOP_CONF_DIR
unset HADOOP_HDFS_HOME
unset HADOOP_HOME
unset HADOOP_MAPRED_HOME
unset HADOOP_OPTS
unset HADOOP_YARN_HOME
unset HIVE_HOME
unset CLASSPATH
unset LD_LIBRARY_PATH

# 设置必要的环境变量
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export HADOOP_PROFILE=hadoop3
export HIVE_PROFILE=hive2.3
export SPARK_LOCAL_IP=localhost
export SKIP_UNIDOC=true
export SKIP_MIMA=true
export SKIP_PACKAGING=true
export CHUKONU_HOME=/root/chukonu/install
export CHUKONU_TEMP=/tmp
export LD_LIBRARY_PATH=/root/chukonu/install/lib:/tmp/cache



# 检查是否传入参数
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <parameter>"
  echo "Valid parameters: sql-a-1 to sql-a-7, sql-b-1, sql-b-2, sql-c-1, sql-c-2, sql-c-3, sql-c-4,sql-c-5, or custom for other options."
  exit 1
fi

# 获取参数
PARAM=$1

# 判断参数是否以 "asan-" 开头，如果是，则去掉前缀
if [[ $PARAM == asan-* ]]; then
  PARAM=${PARAM#asan-}  # 去掉 "asan-" 前缀
  sysctl -w vm.mmap_rnd_bits=28
  export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${CHUKONU_HOME}/lib:${JAVA_HOME}/lib:${JAVA_HOME}/lib/server
else
  echo "Parameter does not start with 'asan-'. Proceeding without asan-specific settings."
  # 在这里添加非 "asan-" 开头时的逻辑
  export LD_PRELOAD=/lib/aarch64-linux-gnu/libjemalloc.so.2:/root/chukonu/install/lib/libchukonu_preloaded.so
  export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${JAVA_HOME}/lib
  export LD_LIBRARY_PATH=/root/chukonu/install/lib:${LD_LIBRARY_PATH}:/tmp/cache
fi


# 根据参数构造命令
case $PARAM in
  hive-1)
    CMD="./dev/run-tests --parallelism 1 --modules hive --included-tags \"org.apache.spark.tags.HivePartOneTest,org.apache.spark.tags.HivePartTwoTest\""
    ;;
  hive-2)
    CMD="./dev/run-tests --parallelism 1 --modules hive --included-tags org.apache.spark.tags.SlowHiveTest"
    ;;
  hive-3)
    CMD="./dev/run-tests --parallelism 1 --modules hive --excluded-tags \"org.apache.spark.tags.HivePartOneTest,org.apache.spark.tags.HivePartTwoTest,org.apache.spark.tags.SlowHiveTest\""
    ;;
  hive-thriftserver-1)
    CMD="./dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartOneTest"
    ;;
  hive-thriftserver-2)
    CMD="./dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartTwoTest"
    ;;
  hive-thriftserver-3)
    CMD="./dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartThreeTest"
    ;;
  hive-thriftserver-4)
    CMD="./dev/run-tests --parallelism 1 --modules hive-thriftserver --included-tags org.apache.spark.tags.HiveThriftServerPartFourTest"
    ;;
  hive-thriftserver-5)
    CMD="./dev/run-tests --parallelism 1 --modules hive-thriftserver --excluded-tags \"org.apache.spark.tags.HiveThriftServerPartOneTest,org.apache.spark.tags.HiveThriftServerPartTwoTest,org.apache.spark.tags.HiveThriftServerPartThreeTest,org.apache.spark.tags.HiveThriftServerPartFourTest\""
    ;;
  sql-a-1)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartOneTest"
    ;;
  sql-a-2)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartTwoTest"
    ;;
  sql-a-3)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartThreeTest"
    ;;
  sql-a-4)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartFourTest"
    ;;
  sql-a-5)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartFiveTest"
    ;;
  sql-a-6)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartSixTest"
    ;;
  sql-a-7)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.ExtendedSQLPartZeroTest"
    ;;
  sql-b-1)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SlowSQLPartOneTest"
    ;;
  sql-b-2)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SlowSQLPartTwoTest"
    ;;
  sql-c-1)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartOneTest"
    ;;
  sql-c-2)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartTwoTest"
    ;;
  sql-c-3)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartThreeTest"
    ;;
  sql-c-4)
    CMD="./dev/run-tests --parallelism 1 --modules sql --included-tags org.apache.spark.tags.SplitSQLPartFourTest"
    ;;
  sql-c-5)
    CMD="./dev/run-tests --parallelism 1 --modules sql --excluded-tags \"org.apache.spark.tags.ExtendedSQLPartOneTest,org.apache.spark.tags.ExtendedSQLPartTwoTest,org.apache.spark.tags.ExtendedSQLPartThreeTest,org.apache.spark.tags.ExtendedSQLPartFourTest,org.apache.spark.tags.ExtendedSQLPartFiveTest,org.apache.spark.tags.SlowSQLPartOneTest,org.apache.spark.tags.SlowSQLPartTwoTest,org.apache.spark.tags.SplitSQLPartOneTest,org.apache.spark.tags.SplitSQLPartTwoTest,org.apache.spark.tags.SplitSQLPartThreeTest,org.apache.spark.tags.SplitSQLPartFourTest,org.apache.spark.tags.ExtendedSQLPartZeroTest,org.apache.spark.tags.ExtendedSQLPartSixTest\""
    ;;
  *)
    echo "Unknown parameter: $PARAM. Defaulting to original logic."
    # 如果参数不是 sql-a-1 到 sql-a-7, sql-b-1, sql-b-2 或 sql-c-1, sql-c-2，sql-c-3,  sql-c-4,sql-c-5 则进入默认逻辑
    MODULES=$PARAM # 假设参数是模块名
    CMD="./dev/run-tests --parallelism 1 --modules $MODULES"
    ;;
esac

# CMD='./build/sbt -Phive "hive/testOnly *HiveWindowFunctionQuerySuite"'
# 执行命令
echo "Running command: $CMD"
eval $CMD