# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe


@frappe.whitelist()
def trigger_categories_sync():
    """
    Manually enqueue a category sync job and return immediately.

    Returns:
        {"queued": True}
    """
    from alaiy_os_cloudstore_connector.cloudstore.sync_categories import run_in_background

    return run_in_background(trigger="manual")


@frappe.whitelist()
def trigger_items_sync():
    """
    Manually enqueue an items sync job and return immediately.

    Returns:
        {"queued": True}
    """
    from alaiy_os_cloudstore_connector.cloudstore.sync_items import run_in_background

    return run_in_background(trigger="manual")


@frappe.whitelist()
def get_sync_status(sync_type: str):
    """
    Return the last 3 Cloudstore Sync Log records for the given sync_type.

    Args:
        sync_type: "categories" or "items"

    Returns:
        List of dicts with fields: name, status, started_at, finished_at,
        items_processed, items_created, items_updated, items_failed,
        pages_total, pages_done, error_message.
    """
    logs = frappe.get_all(
        "Cloudstore Sync Log",
        filters={"sync_type": sync_type},
        fields=[
            "name",
            "status",
            "started_at",
            "finished_at",
            "items_processed",
            "items_created",
            "items_updated",
            "items_failed",
            "pages_total",
            "pages_done",
            "error_message",
        ],
        order_by="started_at desc",
        limit=3,
    )
    return logs
