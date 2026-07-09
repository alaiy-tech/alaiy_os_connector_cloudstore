"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.
"""

connector_meta = {
    "connector_id": "cloudstore",
    "connector_name": "Cloudstore",
    "connector_app": "alaiy_os_connector_cloudstore",
    "connector_type": "supplier",
    "description": "Cloudstore — supplier catalogue, orders & shipping",
    "icon": "store",
    "icon_url": "/assets/alaiy_os_connector_cloudstore/images/cloudstore-icon.svg",
    "settings_doctype": "Cloudstore Connector Settings",
    "test_method": "alaiy_os_connector_cloudstore.api.test_connection.test_connection",
    "sync_categories_method": "alaiy_os_connector_cloudstore.api.sync.trigger_categories_sync",
    "sync_items_method": "alaiy_os_connector_cloudstore.api.sync.trigger_items_sync",
    "sync_status_method": "alaiy_os_connector_cloudstore.api.sync.get_sync_status",
    "sync_categories_label": "Category Tree",
    "sync_items_label": "Items",
    "is_enabled": 0,
    "connection_status": "untested",
}
