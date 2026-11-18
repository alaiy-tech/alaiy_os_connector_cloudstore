"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.
"""

# Columns of Cloudstore Sync Log, named the way the Connector Health page reads them.
_LOG_FIELDS = {
    "processed": "items_processed",
    "changed": ["items_created", "items_updated"],
    "failed": "items_failed",
    "error": "error_message",
}


def _health(key, label, sync_type, interval_setting, expects_rows=True):
    return {
        "key": key,
        "label": label,
        "direction": "pull",
        "log_doctype": "Cloudstore Sync Log",
        "log_filter": {"sync_type": sync_type},
        "fields": _LOG_FIELDS,
        "interval_setting": interval_setting,
        "scheduled": True,
        "expects_rows": expects_rows,
    }


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
    "health": [
        _health("items", "Items sync", "items", "cs_items_sync_interval"),
        _health("stock", "Stock sync", "stock", "cs_stock_sync_interval"),
        _health("categories", "Category sync", "categories", "cs_category_sync_interval"),
        # Orders and events can legitimately have nothing to do.
        _health("orders", "Orders sync", "orders", "cs_orders_sync_interval", expects_rows=False),
        _health("events", "Events sync", "events", "cs_events_sync_interval", expects_rows=False),
    ],
}
