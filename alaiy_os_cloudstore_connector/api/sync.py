import frappe


@frappe.whitelist()
def trigger_categories_sync():
    from alaiy_os_cloudstore_connector.cloudstore.sync_categories import run_in_background
    return run_in_background(trigger="manual")


@frappe.whitelist()
def trigger_items_sync():
    from alaiy_os_cloudstore_connector.cloudstore.sync_items import run_in_background
    return run_in_background(trigger="manual")


@frappe.whitelist()
def get_sync_status(sync_type):
    logs = frappe.get_all(
        "Cloudstore Sync Log",
        filters={"sync_type": sync_type},
        fields=[
            "name", "status", "trigger", "started_at", "finished_at",
            "items_processed", "items_created", "items_updated", "items_failed",
            "pages_total", "pages_done", "error_message",
        ],
        order_by="started_at desc",
        limit=3,
    )
    return logs
