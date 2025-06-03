#!/bin/bash
export JAVA_HOME="/root/jdk-11.0.27+6"
export PATH=$JAVA_HOME/bin:$PATH
cd /io/chukonu/scala && /root/sbt/bin/sbt package
cd /io/chukonu/scala && /root/sbt/bin/sbt assembly
cd /io/chukonu && sed -i 's/find_package(Python REQUIRED COMPONENTS Interpreter Development)/#find_package(Python REQUIRED COMPONENTS Interpreter Development)/g' CMakeLists.txt
cd /io/chukonu && sed -i 's#${JNI_LIBRARIES}#/root/jdk-11.0.27+6/lib/libjsig.so /root/jdk-11.0.27+6/lib/server/libjvm.so#g' CMakeLists.txt
cd /io/chukonu/build && cmake .. -DPython3_ROOT_DIR=/opt/python/cp38-cp38 -DPython_INCLUDE_DIRS=/opt/python/cp38-cp38/include/python3.8 -DPython_LIBRARIES=/opt/rh/rh-python38/root/usr/lib64/libpython3.8.so -DPython_EXECUTABLE=/opt/python/cp38-cp38/bin/python3.8 -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="/io/chukonu/install" -DCMR_BUILD_DEMO=ON -DWITH_JEMALLOC=OFF -DEXPIRE_EPOCH=1759248000
cd /io/chukonu/build && make -j && make install
LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/io/chukonu/install/lib:/opt/rh/rh-python38/root/usr/lib64
cd /io/chukonu/python && /opt/python/cp38-cp38/bin/python setup.py sdist
cd /io/chukonu/python && /opt/python/cp38-cp38/bin/python setup.py bdist_wheel
cd /io/chukonu/python && auditwheel repair dist/chukonu-0.2.0.dev0-py3-none-any.whl \
    --exclude libjsig.so \
    --exclude libjvm.so \
    --plat manylinux2014_aarch64 -w ./wheelhouse