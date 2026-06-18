app_name = "alaiy_os_cloudstore_connector"
app_title = "AlaiyOS Cloudstore Connector"
app_publisher = "AlaiyOS"
app_description = "Cloudstore (The Corner, Italy) supplier connector for AlaiyOS"
app_email = "dev@alaiy.com"
app_license = "MIT"

# Register/update this connector in OS Connector Registry after every migration
after_migrate = [
    "alaiy_os_cloudstore_connector.setup.install.sync_connector_registry"
]
