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
    from alaiy_os_connector_cloudstore.cloudstore.sync_categories import run_in_background

    return run_in_background(trigger="manual")


@frappe.whitelist()
def trigger_items_sync():
    """
    Manually enqueue an items sync job and return immediately.

    Returns:
        {"queued": True}
    """
    from alaiy_os_connector_cloudstore.cloudstore.sync_items import run_in_background

    return run_in_background(trigger="manual")


@frappe.whitelist()
def get_sync_status(sync_type: str):
    """
    Return the last 3 Cloudstore Sync Log records for the given sync_type.

    Args:
        sync_type: "categories", "items", "orders" or "events"

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


@frappe.whitelist()
def lookup_item(sku: str = None, parent_sku: str = None):
    """
    Read one variant (sku) or all variants of a product (parent_sku) straight
    from Cloudstore. Nothing is written to ERPNext.
    """
    frappe.only_for(("System Manager", "Stock Manager"))
    from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient

    client = CloudstoreClient()
    if parent_sku:
        return client.items.list_by_parent_skus([parent_sku])
    if sku:
        return client.items.find_by_code(sku)
    frappe.throw("Pass sku or parent_sku.")


@frappe.whitelist()
def trigger_orders_sync():
    """Manually enqueue an order status refresh and return immediately."""
    frappe.only_for(("System Manager", "Sales Manager"))
    frappe.enqueue(
        "alaiy_os_connector_cloudstore.cloudstore.sync_orders.run",
        queue="long",
        trigger="manual",
    )
    return {"queued": True}


@frappe.whitelist()
def push_sales_order(sales_order: str):
    """Send (or retry) one Sales Order to Cloudstore."""
    frappe.only_for(("System Manager", "Sales Manager"))
    from alaiy_os_connector_cloudstore.cloudstore.sync_orders import push_order

    return push_order(sales_order)


@frappe.whitelist()
def trigger_events_sync():
    """Manually enqueue an events run (stock push if enabled, then event poll)."""
    frappe.only_for(("System Manager", "Stock Manager"))
    frappe.enqueue(
        "alaiy_os_connector_cloudstore.cloudstore.sync_events.run",
        queue="long",
        trigger="manual",
    )
    return {"queued": True}


@frappe.whitelist()
def trigger_stock_sync():
    """Manually enqueue a stock only sync and return immediately."""
    frappe.only_for(("System Manager", "Stock Manager"))
    frappe.enqueue(
        "alaiy_os_connector_cloudstore.cloudstore.sync_stock.run",
        queue="long",
        trigger="manual",
    )
    return {"queued": True}
