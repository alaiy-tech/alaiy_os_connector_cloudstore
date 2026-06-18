from setuptools import setup, find_packages

setup(
    name="alaiy_os_cloudstore_connector",
    version="0.0.1",
    description="AlaiyOS — Cloudstore Connector (The Corner, Italy)",
    author="AlaiyOS",
    author_email="dev@alaiy.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=["requests>=2.28.0"],
)
