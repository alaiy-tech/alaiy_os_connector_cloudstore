# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, now_datetime, nowdate

from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient
from alaiy_os_connector_cloudstore.cloudstore.order_payload import (
    build_order_payload,
    cloudstore_lines,
)

# Orders are not tracked past this age by the status refresh.
_REFRESH_WINDOW_DAYS = 30


def on_sales_order_submit(doc, method=None):
    """doc_events hook: queue the push so the submit itself never waits on Cloudstore."""
    if not frappe.db.get_single_value("Cloudstore Connector Settings", "cs_push_orders"):
        return
    frappe.enqueue(
        "alaiy_os_connector_cloudstore.cloudstore.sync_orders.push_order",
        queue="short",
        sales_order=doc.name,
        enqueue_after_commit=True,
    )


def on_sales_order_cancel(doc, method=None):
    """doc_events hook: a cancelled Sales Order that was sent is cancelled on Cloudstore too."""
    if not frappe.db.get_single_value("Cloudstore Connector Settings", "cs_push_orders"):
        return
    if not doc.get("cs_order_id"):
        return
    frappe.enqueue(
        "alaiy_os_connector_cloudstore.cloudstore.sync_orders.cancel_order",
        queue="short",
        sales_order=doc.name,
        enqueue_after_commit=True,
    )


def cancel_order(sales_order: str) -> dict:
    """
    DELETE the order on Cloudstore. Cloudstore keeps it, marks it CANCELED and
    gives the allocated quantities back for sale. (PATCH to CANCELED is
    deprecated by Cloudstore.)
    """
    so = frappe.get_doc("Sales Order", sales_order)
    if not so.get("cs_order_id"):
        return {"skipped": "never pushed"}
    try:
        CloudstoreClient().orders.delete(so.cs_order_id)
        _store(so.name, cs_order_status="CANCELED", cs_push_error="")
        return {"cancelled": so.cs_order_id}
    except Exception as exc:
        _store(so.name, cs_push_error=f"Cancel failed: {exc}"[:500])
        frappe.log_error(title=f"Cloudstore order cancel failed: {so.name}", message=frappe.get_traceback())
        return {"error": str(exc)}


def push_order(sales_order: str) -> dict:
    """
    Send one Sales Order to Cloudstore (create), or do nothing if it was
    already sent. Only the Cloudstore-sourced lines are sent. The result is
    stored on the Sales Order (cs_order_id, cs_order_status, cs_push_error).
    """
    so = frappe.get_doc("Sales Order", sales_order)
    if so.get("cs_order_id"):
        return {"skipped": "already pushed", "cs_order_id": so.cs_order_id}

    lines = cloudstore_lines(so)
    if not lines:
        return {"skipped": "no Cloudstore items"}

    try:
        client = CloudstoreClient()
        record = _record(client.orders.create(build_order_payload(so, lines)))
        order_id = _oid(record, "_id")
        if not order_id:  # fall back to reading it back by our own key
            record = _record(client.orders.find_by_shop_order_id(so.name))
            order_id = _oid(record, "_id")
        if not order_id:
            raise RuntimeError(f"Order created but no id in Cloudstore reply: {str(record)[:300]}")
        _store(so.name, cs_order_id=order_id, cs_order_status=record.get("order_status") or "", cs_push_error="")
        return {"cs_order_id": order_id}
    except Exception as exc:
        _store(so.name, cs_push_error=str(exc)[:500])
        frappe.log_error(title=f"Cloudstore order push failed: {so.name}", message=frappe.get_traceback())
        return {"error": str(exc)}


def refresh_order_statuses() -> dict:
    """Pull the current Cloudstore status for recently pushed Sales Orders."""
    names = frappe.get_all(
        "Sales Order",
        filters={"cs_order_id": ["is", "set"], "transaction_date": [">=", add_days(nowdate(), -_REFRESH_WINDOW_DAYS)]},
        pluck="name",
    )
    client = CloudstoreClient()
    stats = {"checked": 0, "changed": 0, "failed": 0}
    for name in names:
        stats["checked"] += 1
        try:
            record = _record(client.orders.find_by_shop_order_id(name))
            status = record.get("order_status")
            if status and status != frappe.db.get_value("Sales Order", name, "cs_order_status"):
                _store(name, cs_order_status=status)
                stats["changed"] += 1
        except Exception:
            stats["failed"] += 1
            frappe.log_error(title=f"Cloudstore order status failed: {name}", message=frappe.get_traceback())
    frappe.db.commit()
    return stats


def run(trigger: str = "scheduled") -> str:
    """Background job: refresh statuses and record the run in Cloudstore Sync Log."""
    log = frappe.new_doc("Cloudstore Sync Log")
    log.sync_type = "orders"
    log.trigger = trigger
    log.status = "running"
    log.started_at = now_datetime()
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    try:
        stats = refresh_order_statuses()
        log.items_processed = stats["checked"]
        log.items_updated = stats["changed"]
        log.items_failed = stats["failed"]
        log.status = "success"
    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)[:1000]
        frappe.log_error(title="Cloudstore orders sync failed", message=frappe.get_traceback())
    finally:
        log.finished_at = now_datetime()
        log.save(ignore_permissions=True)
        frappe.db.commit()
    return log.name


def apply_order_event(shop_order_id: str, new_status: str = None, shipment: dict = None) -> bool:
    """
    Apply a Cloudstore order event to its Sales Order: new status, and carrier,
    tracking and shipment status when a shipment is attached. The Sales Order is
    found by shop_order_id (our Sales Order name), else through the Cloudstore
    order ids listed on the shipment. Returns False when none matches.
    """
    name = shop_order_id if shop_order_id and frappe.db.exists("Sales Order", shop_order_id) else None
    if not name and shipment:
        for linked in shipment.get("orders") or []:
            oid = (linked.get("order_id") or {}).get("$oid")
            name = oid and frappe.db.get_value("Sales Order", {"cs_order_id": oid}, "name")
            if name:
                break
    if not name:
        return False

    values = {}
    if new_status:
        values["cs_order_status"] = new_status
    if shipment:
        history = shipment.get("status_history") or []
        values["cs_carrier"] = shipment.get("carrier") or ""
        values["cs_tracking_number"] = shipment.get("tracking_number") or ""
        values["cs_tracking_url"] = shipment.get("tracking_url") or ""
        values["cs_shipment_status"] = (history[-1].get("status") if history else "") or ""
    if values:
        _store(name, **values)
    return True


def _store(sales_order: str, **values):
    # Tracking fields only (read-only, allow_on_submit): no document hooks to fire.
    frappe.db.set_value("Sales Order", sales_order, values, update_modified=False)
    frappe.db.commit()


def _record(resp) -> dict:
    """The Order object of a reply: {"content": Order} (EntitySingleResponseOrder)."""
    content = resp.get("content") if isinstance(resp, dict) else None
    return content if isinstance(content, dict) else {}


def _oid(record: dict, *keys) -> str:
    """Id under the first present key; Cloudstore ids are plain strings or {"$oid": ...}."""
    for key in keys:
        val = record.get(key)
        if isinstance(val, dict):
            val = val.get("$oid")
        if val:
            return str(val)
    return ""
