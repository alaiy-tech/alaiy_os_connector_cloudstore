app_name = "alaiy_os_cloudstore_connector"
app_title = "Alaiy OS Cloudstore Connector"
app_publisher = "Alaiy"
app_description = "Cloudstore supplier connector for Alaiy OS"
app_email = "dev@alaiy.com"
app_license = "MIT"

required_apps = ["alaiy_os_core", "erpnext"]

after_migrate = [
    "alaiy_os_cloudstore_connector.setup.install.sync_connector_registry"
]

# Register the Cloudstore Sync Log in the Alaiy OS "Logs" sidebar section.
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
