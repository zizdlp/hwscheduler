from setuptools import setup, find_packages

setup(
    name="hwscheduler",
    version="0.3",
    packages=find_packages(exclude=["tests*"]),
    install_requires=[ 
        "huaweicloudsdkcore==3.1.149",
        "huaweicloudsdkecs==3.1.149",
        "huaweicloudsdkeip==3.1.149",
        "fabric==3.2.2",
        "rich==14.0.0"
    ],
    python_requires=">=3.6",  # 添加Python版本要求

)