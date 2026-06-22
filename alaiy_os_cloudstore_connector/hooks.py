app_name = "alaiy_os_cloudstore_connector"
app_title = "AlaiyOS Cloudstore Connector"
app_publisher = "AlaiyOS"
app_description = "Cloudstore (The Corner, Italy) supplier connector for AlaiyOS"
app_email = "dev@alaiy.com"
app_license = "MIT"

after_migrate = [
    "alaiy_os_cloudstore_connector.setup.install.sync_connector_registry"
]

# Register the Cloudstore Sync Log in the AlaiyOS "Logs" sidebar section.
# alaiy_os_core reads this hook in create_or_update_workspace_sidebar().
alaiy_os_sidebar_log_items = [
    {"link_type": "DocType", "link_to": "Cloudstore Sync Log",
     "label": "Cloudstore Logs", "icon": "activity"}
]

scheduler_events = {
    "cron": {
        "* * * * *": [
            "alaiy_os_cloudstore_connector.cloudstore.sync_jobs.check_and_enqueue"
        ]
    }
}
