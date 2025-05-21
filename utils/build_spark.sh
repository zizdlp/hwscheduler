# 设置必要的环境变量
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64
export CHUKONU_HOME=/root/chukonu/install
export CHUKONU_TEMP=/tmp
export LD_LIBRARY_PATH=/root/chukonu/install/lib:/tmp/cache
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
sbt package
cd python
python3 setup.py sdist
pip install dist/pyspark-3.4.4.dev0.tar.gz 