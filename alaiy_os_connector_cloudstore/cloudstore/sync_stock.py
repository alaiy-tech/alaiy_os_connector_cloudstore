# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""
Stock only sync. Reads /items with quantities and, for items that already
exist in ERPNext:

1. keeps Cloudstore's own numbers on the Item (Item Supplier Attribute rows
   cloudstore_qty, cloudstore_stock per warehouse, cloudstore_stock_at), so
   they stay available after our own sales change the ERPNext stock
2. sets the ERPNext stock to the Cloudstore quantity with Stock
   Reconciliation, only where the number actually differs

It never creates or edits Items, so it is much lighter than the items sync.
"""

import json

import frappe
from frappe.utils import now_datetime

from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient
from alaiy_os_connector_cloudstore.cloudstore.sync_items import (
    _build_stock_entries,
    _ensure_warehouse,
    _submit_stock_reconciliation,
)

_RECONCILE_CHUNK = 200


def run(trigger: str = "scheduled") -> str:
    """Background job. One Cloudstore Sync Log row, sync type "stock"."""
    log = frappe.new_doc("Cloudstore Sync Log")
    log.sync_type = "stock"
    log.trigger = trigger
    log.status = "running"
    log.started_at = now_datetime()
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        settings = frappe.get_single("Cloudstore Connector Settings")
        default_warehouse = _ensure_warehouse((settings.cs_sync_warehouse or "").strip())
        wh_cache = {row.cs_wh_id: row.warehouse for row in (settings.cs_warehouse_mapping or [])}
        supplier = (settings.cs_supplier or "").strip()

        stats = {"seen": 0, "unknown": 0, "changed": 0, "failed": 0}
        changed_entries = []

        for content, metadata in CloudstoreClient().items.paginated():
            if not log.pages_total:
                log.pages_total = int(metadata.get("total_pages", 0))

            known = set(frappe.get_all(
                "Item", filters={"name": ["in", [i.get("sku") for i in content if i.get("sku")]]}, pluck="name"
            ))
            for item_data in content:
                sku = item_data.get("sku")
                stats["seen"] += 1
                if sku not in known:
                    stats["unknown"] += 1
                    continue
                try:
                    entries = _build_stock_entries(sku, item_data, settings, wh_cache, default_warehouse)
                    if supplier:
                        _store_cloudstore_stock(sku, supplier, item_data)
                    changed = _only_changed(entries)
                    changed_entries += changed
                    stats["changed"] += 1 if changed else 0
                except Exception as exc:
                    stats["failed"] += 1
                    _append(log, f"ERROR sku={sku}: {exc}")
                    frappe.log_error(title=f"Cloudstore stock error: {sku}", message=frappe.get_traceback())

            log.pages_done += 1
            log.items_processed = stats["seen"]
            log.items_updated = stats["changed"]
            log.items_failed = stats["failed"]
            log.save(ignore_permissions=True)
            frappe.db.commit()

        stock_error = ""
        for i in range(0, len(changed_entries), _RECONCILE_CHUNK):
            try:
                _submit_stock_reconciliation(changed_entries[i:i + _RECONCILE_CHUNK])
            except Exception as exc:
                stock_error = str(exc)
                _append(log, f"ERROR: Stock Reconciliation failed: {exc}")
                frappe.log_error(title="Cloudstore stock reconciliation failed", message=frappe.get_traceback())

        _append(log, f"Seen {stats['seen']}, not in ERPNext {stats['unknown']}, stock changed on {stats['changed']}.")
        if stock_error:
            log.status = "failed"
            log.error_message = f"Stock was not updated: {stock_error}"[:1000]
        else:
            log.status = "success"
    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)[:1000]
        frappe.log_error(title="Cloudstore stock sync failed", message=frappe.get_traceback())
    finally:
        log.finished_at = now_datetime()
        log.save(ignore_permissions=True)
        frappe.db.commit()
    return log.name


def _only_changed(entries: list) -> list:
    """Entries whose quantity differs from what ERPNext holds now (no Bin counts as 0)."""
    changed = []
    for e in entries:
        if not e.get("warehouse"):
            continue
        current = frappe.db.get_value("Bin", {"item_code": e["item_code"], "warehouse": e["warehouse"]}, "actual_qty") or 0
        if float(current) != float(e["qty"]):
            changed.append(e)
    return changed


def _store_cloudstore_stock(sku: str, supplier: str, item_data: dict):
    """Cloudstore's own quantities on the Item, written only when they changed."""
    whs = [{"wh_id": (w.get("wh_id") or {}).get("$oid"), "qty": w.get("qty")} for w in (item_data.get("whs") or [])]
    values = {
        "cloudstore_qty": str(item_data.get("qty") if item_data.get("qty") is not None else sum(w["qty"] or 0 for w in whs)),
        "cloudstore_stock": json.dumps(whs),
        "cloudstore_stock_at": str(now_datetime()),
    }
    for key, value in values.items():
        _set_attribute(sku, supplier, key, value, only_if_changed=key != "cloudstore_stock_at")


def _set_attribute(item_code: str, supplier: str, key: str, value: str, only_if_changed: bool = True):
    filters = {"parent": item_code, "supplier": supplier, "connector_name": "cloudstore", "attribute_key": key}
    row = frappe.db.get_value("Item Supplier Attribute", filters, ["name", "attribute_value"], as_dict=True)
    if row:
        if not (only_if_changed and row.attribute_value == value):
            frappe.db.set_value("Item Supplier Attribute", row.name, "attribute_value", value, update_modified=False)
        return
    frappe.get_doc({
        "doctype": "Item Supplier Attribute",
        "parent": item_code,
        "parenttype": "Item",
        "parentfield": "supplier_attributes",
        "supplier": supplier,
        "connector_name": "cloudstore",
        "attribute_key": key,
        "attribute_value": value,
    }).insert(ignore_permissions=True)


def _append(log, message: str):
    log.log_messages = ((log.log_messages or "") + "\n" + message).strip()
