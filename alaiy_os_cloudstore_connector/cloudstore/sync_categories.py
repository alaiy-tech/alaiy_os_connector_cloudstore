# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime

from alaiy_os_cloudstore_connector.cloudstore.client import CloudstoreClient


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run(trigger: str = "scheduled") -> str:
    """
    Synchronise the Cloudstore category tree into ERPNext Item Groups.

    Creates a Cloudstore Sync Log, fetches /categories/tree, recursively
    upserts Item Groups, then marks the log success or failed.

    Returns:
        The name (ID) of the Cloudstore Sync Log document.
    """
    log = frappe.new_doc("Cloudstore Sync Log")
    log.sync_type = "categories"
    log.trigger = trigger
    log.status = "running"
    log.started_at = now_datetime()
    log.items_processed = 0
    log.items_created = 0
    log.items_updated = 0
    log.items_failed = 0
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        _ensure_root_item_group()
        client = CloudstoreClient()
        tree = client.get("/categories/tree")

        stats = {"processed": 0, "created": 0, "updated": 0, "failed": 0}
        _sync_tree(tree, "All Item Groups", log, stats)

        log.items_processed = stats["processed"]
        log.items_created = stats["created"]
        log.items_updated = stats["updated"]
        log.items_failed = stats["failed"]
        log.status = "success"

    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)[:1000]
        frappe.log_error(
            title="Cloudstore category sync failed",
            message=frappe.get_traceback(),
        )

    finally:
        log.finished_at = now_datetime()
        log.save(ignore_permissions=True)
        frappe.db.commit()

    return log.name


def run_in_background(trigger: str = "manual") -> dict:
    """
    Enqueue a category sync job on the long queue and return immediately.

    Returns:
        {"queued": True}
    """
    frappe.enqueue(
        "alaiy_os_cloudstore_connector.cloudstore.sync_categories.run",
        queue="long",
        trigger=trigger,
    )
    return {"queued": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_root_item_group():
    """Create the ERPNext root Item Group if it doesn't exist yet."""
    if frappe.db.exists("Item Group", "All Item Groups"):
        return
    root = frappe.new_doc("Item Group")
    root.item_group_name = "All Item Groups"
    root.is_group = 1
    root.insert(ignore_permissions=True)
    frappe.db.commit()


def _sync_tree(nodes: list, parent_name: str, log, stats: dict = None):
    """
    Recursively upsert Cloudstore category nodes as ERPNext Item Groups.

    Args:
        nodes:       List of category dicts from the Cloudstore API tree.
        parent_name: ERPNext name of the parent Item Group for this level.
        log:         The live Cloudstore Sync Log document (updated in-place).
        stats:       Mutable dict with keys processed/created/updated/failed.
    """
    if stats is None:
        stats = {"processed": 0, "created": 0, "updated": 0, "failed": 0}

    for node in nodes:
        oid = (node.get("id") or {}).get("$oid") or ""
        node_name = (node.get("name") or "").strip()
        level = node.get("level", 0)
        children = node.get("children") or []

        if not oid or not node_name:
            stats["failed"] += 1
            continue

        try:
            existing_name = frappe.db.get_value(
                "Item Group",
                {"cs_cloudstore_id": oid},
                "name",
            )
            # Fall back to name match so we adopt existing groups instead of
            # failing with a duplicate-key error.
            if not existing_name:
                existing_name = frappe.db.get_value("Item Group", node_name, "name")

            if existing_name:
                doc = frappe.get_doc("Item Group", existing_name)
                doc.item_group_name = node_name
                doc.parent_item_group = parent_name
                doc.cs_cloudstore_id = oid
                doc.cs_cat_level = level
                doc.is_group = 1 if children else 0
                doc.save(ignore_permissions=True)
                stats["updated"] += 1
            else:
                doc = frappe.new_doc("Item Group")
                doc.item_group_name = node_name
                doc.parent_item_group = parent_name
                doc.cs_cloudstore_id = oid
                doc.cs_cat_level = level
                doc.is_group = 1 if children else 0
                doc.insert(ignore_permissions=True)
                existing_name = doc.name
                stats["created"] += 1

            stats["processed"] += 1

            # Commit every 10 nodes to avoid long transactions
            if stats["processed"] % 10 == 0:
                frappe.db.commit()

            # Persist progress to log every 20 nodes
            if stats["processed"] % 20 == 0:
                log.items_processed = stats["processed"]
                log.items_created = stats["created"]
                log.items_updated = stats["updated"]
                log.items_failed = stats["failed"]
                log.save(ignore_permissions=True)
                frappe.db.commit()

            # Recurse into children using the just-upserted group as parent
            if children:
                _sync_tree(children, existing_name, log, stats)

        except Exception as exc:
            stats["failed"] += 1
            _append_log(log, f"ERROR node {oid} ({node_name}): {exc}")
            frappe.log_error(
                title=f"Cloudstore category sync error: {node_name}",
                message=frappe.get_traceback(),
            )


def _append_log(log, message: str):
    """Append a line to log.log_messages without saving."""
    existing = log.log_messages or ""
    log.log_messages = (existing + "\n" + message).strip()
