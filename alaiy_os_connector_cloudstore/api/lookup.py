# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe

_ROLES = ("System Manager", "Stock Manager")


@frappe.whitelist()
def search_items(term: str):
    """Search Cloudstore items by free text. Saves nothing."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_cloudstore.cloudstore.sync_item_lookup import search

    return search(term)


@frappe.whitelist()
def find_items(code: str, partial: int = 0, code_type: str = "SKU"):
    """
    Look items up by code. code_type: SKU, SKU_PARENT, BARCODE, EAN, MNF_CODE, MPN,
    UPC, ITEM_ID. partial=1 matches part of the code. Saves nothing.
    """
    frappe.only_for(_ROLES)
    from alaiy_os_connector_cloudstore.cloudstore.sync_item_lookup import find

    return find(code, partial=bool(int(partial)), code_type=code_type)


@frappe.whitelist()
def sync_skus(skus):
    """Store these variants. skus: JSON list or comma separated."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_cloudstore.cloudstore.sync_item_lookup import sync_skus as run

    return run(_as_list(skus))


@frappe.whitelist()
def sync_parents(parent_skus):
    """Store every size of these products. parent_skus: JSON list or comma separated."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_cloudstore.cloudstore.sync_item_lookup import sync_parents as run

    return run(_as_list(parent_skus))


@frappe.whitelist()
def sync_filtered(brands=None, category_ids=None, warehouse_ids=None):
    """Store only products of these brands, Cloudstore category ids and/or warehouse ids."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_cloudstore.cloudstore.sync_filtered import sync_filtered as run

    return run(_as_list(brands), _as_list(category_ids), _as_list(warehouse_ids))


@frappe.whitelist()
def browse_categories(parent_id: str = None):
    """Cloudstore root categories, or the children of parent_id."""
    frappe.only_for(_ROLES)
    from alaiy_os_connector_cloudstore.cloudstore.category_browse import browse

    return browse(parent_id)


def _as_list(value) -> list:
    if not value:
        return []
    if isinstance(value, str):
        value = frappe.parse_json(value) if value.strip().startswith("[") else value.split(",")
    return [str(v).strip() for v in value if str(v).strip()]
