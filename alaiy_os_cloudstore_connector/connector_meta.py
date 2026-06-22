"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os_core's OS Connector Registry.
"""

connector_meta = {
    "connector_id": "cloudstore",
    "connector_name": "Cloudstore",
    "connector_app": "alaiy_os_cloudstore_connector",
    "connector_type": "supplier",
    "description": "The Corner, Italy — supplier catalogue, orders & shipping",
    "icon": "store",
    "icon_url": "/assets/alaiy_os_cloudstore_connector/images/cloudstore-icon.svg",
    "settings_doctype": "Cloudstore Connector Settings",
    "test_method": "alaiy_os_cloudstore_connector.api.test_connection.test_connection",
    "sync_categories_method": "alaiy_os_cloudstore_connector.api.sync.trigger_categories_sync",
    "sync_items_method": "alaiy_os_cloudstore_connector.api.sync.trigger_items_sync",
    "is_enabled": 0,
    "connection_status": "untested",
}
