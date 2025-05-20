# 调度

```sh
apt update
apt install -y build-essential  # 修正为 build-essential
apt install -y openssh-client
apt install -y python3
apt install -y python3-pip
pip install huaweicloudsdkcore huaweicloudsdkecs huaweicloudsdkeip fabric
```

```
export JAVA_HOME="/usr/lib/jvm/java-11-openjdk-arm64"
export CHUKONU_HOME="/root/chukonu/install"
export LD_LIBRARY_PATH=/root/chukonu/install/lib:/tmp/cache
export CHUKONU_TEMP=/tmp
cd scala && sbt package
cd scala && sbt assembly
mkdir build && mkdir /tmp/cache && mkdir /tmp/staging
cd build && cmake .. -DCMAKE_BUILD_TYPE=Debug -DWITH_ASAN=OFF -DWITH_JEMALLOC=OFF -DCMAKE_INSTALL_PREFIX="$CHUKONU_HOME"
cd build && make install
cd build && ctest
cd scala && ~/.local/share/coursier/bin/sbt test
```


```
curl -X POST \
  -H "Authorization: token ${github_token}" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/chukonu-team/chukonu/actions/runners/registration-token"
```