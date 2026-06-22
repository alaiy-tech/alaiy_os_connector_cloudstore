app_name = "alaiy_os_cloudstore_connector"
app_title = "AlaiyOS Cloudstore Connector"
app_publisher = "AlaiyOS"
app_description = "Cloudstore (The Corner, Italy) supplier connector for AlaiyOS"
app_email = "dev@alaiy.com"
app_license = "MIT"

after_migrate = [
    "alaiy_os_cloudstore_connector.setup.install.sync_connector_registry"
]

scheduler_events = {
    "cron": {
        "* * * * *": [
            "alaiy_os_cloudstore_connector.cloudstore.sync_jobs.check_and_enqueue"
        ]
    }
}
