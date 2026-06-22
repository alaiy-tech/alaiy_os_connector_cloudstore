import frappe
from frappe.utils import now_datetime, add_to_date


_INTERVAL_MINUTES = {
    "1 min": 1,
    "5 min": 5,
    "10 min": 10,
    "30 min": 30,
}


def check_and_enqueue():
    """
    Called every minute by the Frappe scheduler.
    Checks each sync type against the configured interval and enqueues if due.
    """
    if not frappe.db.exists("DocType", "Cloudstore Sync Log"):
        return

    settings = frappe.get_single("Cloudstore Connector Settings")

    _maybe_enqueue(
        settings.cs_category_sync_interval,
        sync_type="categories",
        enqueue_fn="alaiy_os_cloudstore_connector.cloudstore.sync_categories.run",
    )
    _maybe_enqueue(
        settings.cs_items_sync_interval,
        sync_type="items",
        enqueue_fn="alaiy_os_cloudstore_connector.cloudstore.sync_items.run",
    )


def _maybe_enqueue(interval_setting, sync_type, enqueue_fn):
    interval_minutes = _INTERVAL_MINUTES.get(interval_setting)
    if not interval_minutes:
        return

    now = now_datetime()

    # If there's a running job started within the last 30 min, skip
    running = frappe.db.get_value(
        "Cloudstore Sync Log",
        {"sync_type": sync_type, "status": "running"},
        "started_at",
        order_by="started_at desc",
    )
    if running and (now - running).total_seconds() < 1800:
        return

    # Check when the last successful run started
    last_success = frappe.db.get_value(
        "Cloudstore Sync Log",
        {"sync_type": sync_type, "status": "success"},
        "started_at",
        order_by="started_at desc",
    )
    if last_success:
        due_at = add_to_date(last_success, minutes=interval_minutes)
        if now < due_at:
            return

    frappe.enqueue(enqueue_fn, queue="long", trigger="scheduled")
