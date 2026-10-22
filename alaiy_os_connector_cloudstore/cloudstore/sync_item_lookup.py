# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""On-demand item work: search Cloudstore, look an item up, sync chosen items only."""

import frappe

from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient
from alaiy_os_connector_cloudstore.cloudstore.sync_items import upsert_batch


def search(term: str, page_size: int = 50) -> list:
    """Free-text search on Cloudstore (listBySearchTerm). Nothing is saved."""
    return [_summary(i) for i in _items(CloudstoreClient().items.search(term, page_size))]


def find(code: str, partial: bool = False, code_type: str = "SKU") -> list:
    """
    Lookup by code (listByCode). code_type: SKU, SKU_PARENT, BARCODE, EAN, MNF_CODE,
    MPN, UPC, ITEM_ID. The server default is a partial, case-insensitive match,
    so EXACT is requested unless partial=True. Nothing is saved.
    """
    search_type = "PARTIAL_CASE_INSENSITIVE" if partial else "EXACT"
    return [
        _summary(i)
        for i in _items(CloudstoreClient().items.list_by_code(code, code_type=code_type, search_type=search_type))
    ]


def sync_skus(skus: list) -> dict:
    """Store these exact variants (findByCode each)."""
    client = CloudstoreClient()
    found = []
    for sku in skus:
        found += [i for i in _items(client.items.find_by_code(sku)) if i.get("sku") == sku]
    return _store(found, wanted=len(skus))


def sync_parents(parent_skus: list) -> dict:
    """Store every size of these products (listByParentSKUList)."""
    found = _items(CloudstoreClient().items.list_by_parent_skus(parent_skus))
    return _store(found, wanted=len(parent_skus))


def _store(found: list, wanted: int) -> dict:
    if not found:
        frappe.throw("Cloudstore returned no matching items.")
    stats = upsert_batch(found)
    stats["requested"] = wanted
    return stats


def _items(resp) -> list:
    """
    Item objects from a reply. Cloudstore wraps everything in an envelope:
    list calls give {"content": [items]}, single calls {"content": item}.
    """
    content = resp.get("content") if isinstance(resp, dict) else resp
    if isinstance(content, list):
        return content
    return [content] if isinstance(content, dict) and content.get("sku") else []


def _summary(item: dict) -> dict:
    singles = (item.get("locs") or {}).get("singles") or {}
    title = singles.get("title") or {}
    return {
        "sku": item.get("sku"),
        "sku_parent": (item.get("props") or {}).get("sku_parent"),
        "title": title.get("en") or next(iter(title.values()), ""),
        "brand": (item.get("props") or {}).get("brand"),
        "qty": item.get("qty"),
        "sale_price": item.get("sale_price"),
        "stock_price": item.get("stock_price"),
        "exists_in_erp": bool(item.get("sku") and frappe.db.exists("Item", item["sku"])),
    }
