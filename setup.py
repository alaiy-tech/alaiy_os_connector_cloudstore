from setuptools import setup, find_packages

setup(
    name="alaiy_os_connector_cloudstore",
    version="0.0.1",
    description="Alaiy OS — Cloudstore Connector",
    author="Alaiy",
    author_email="dev@alaiy.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=["requests>=2.28.0"],
)
