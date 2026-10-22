# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""Sync only the products matching a filter, instead of the whole catalogue."""

import frappe

from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient
from alaiy_os_connector_cloudstore.cloudstore.sync_items import upsert_batch


def build_filter(brands: list = None, category_ids: list = None, warehouse_ids: list = None) -> dict:
    """
    Body for listParentsByFilter (CSApiParentItemFilterV2). Each field is
    {"values": [...], "op": "IN"}. Brands match case-sensitively; categories
    include their subcategories. All given conditions must hold.
    """
    filters = {}
    if brands:
        filters["brands"] = {"values": list(brands), "op": "IN"}
    if category_ids:
        filters["cat_ids"] = {"values": [{"$oid": c} for c in category_ids], "op": "IN"}
    if warehouse_ids:
        filters["whs_ids"] = {"values": [{"$oid": w} for w in warehouse_ids], "op": "IN"}
    if not filters:
        frappe.throw("Give at least one brand, category or warehouse.")
    return filters


def sync_filtered(brands: list = None, category_ids: list = None, warehouse_ids: list = None,
                  max_parents: int = 500) -> dict:
    """
    Page through the parent products matching the filter and store every size
    of each (the reply already carries the items). Stops at max_parents so one
    call cannot pull the whole catalogue.
    """
    client = CloudstoreClient()
    filters = build_filter(brands, category_ids, warehouse_ids)

    stats = {"processed": 0, "created": 0, "updated": 0, "failed": 0, "errors": [], "parents": 0}
    page = 0
    while stats["parents"] < max_parents:
        resp = client.items.list_parents_by_filter(filters, page_index=page, page_size=50)
        parents = resp.get("content") or []
        if not parents:
            break
        items = [item for parent in parents for item in (parent.get("items") or [])]
        stats["parents"] += len(parents)
        if items:
            part = upsert_batch(items)
            for key in ("processed", "created", "updated", "failed"):
                stats[key] += part[key]
            stats["errors"] += part["errors"]
        page += 1
        if page >= int((resp.get("_metadata") or {}).get("total_pages", 1)):
            break

    if not stats["parents"]:
        frappe.throw("No products match this filter.")
    return stats
