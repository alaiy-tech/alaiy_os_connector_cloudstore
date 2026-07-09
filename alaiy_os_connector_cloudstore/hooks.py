app_name = "alaiy_os_connector_cloudstore"
app_title = "Alaiy OS Connector Cloudstore Connector"
app_publisher = "Alaiy"
app_description = "Cloudstore supplier connector for Alaiy OS"
app_email = "dev@alaiy.com"
app_license = "MIT"

required_apps = ["alaiy_os", "erpnext"]

after_install = [
    "alaiy_os_connector_cloudstore.setup.install.after_install"
]

after_migrate = [
    "alaiy_os_connector_cloudstore.setup.install.sync_connector_registry"
]

# Register the Cloudstore Sync Log in the Alaiy OS "Logs" sidebar section.
# alaiy_os reads this hook in create_or_update_workspace_sidebar().
alaiy_os_sidebar_log_items = [
    {"link_type": "DocType", "link_to": "Cloudstore Sync Log",
     "label": "Cloudstore Logs", "icon": "activity"}
]

scheduler_events = {
    "cron": {
        "* * * * *": [
            "alaiy_os_connector_cloudstore.cloudstore.sync_jobs.check_and_enqueue"
        ]
    }
}
