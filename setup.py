from setuptools import setup, find_packages
import os
def read_requirements():
    with open(os.path.join(os.path.dirname(__file__), 'requirements.txt')) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]
setup(
    name="scheduler",
    version="0.1",
    packages=find_packages(exclude=["tests*"]),
    install_requires=read_requirements(),
    # 其他元数据...
)