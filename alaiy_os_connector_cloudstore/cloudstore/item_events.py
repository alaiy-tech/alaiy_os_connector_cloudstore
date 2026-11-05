# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""Apply Cloudstore item events (stock, price, catalogue, removal) to ERPNext."""

import frappe

from alaiy_os_connector_cloudstore.cloudstore.sync_items import (
    _non_negative,
    _submit_stock_reconciliation,
    _upsert_price,
    upsert_batch,
)
from alaiy_os_connector_cloudstore.cloudstore.sync_stock import _only_changed

PRICE_EVENTS = ("ITEMS_PRICE_UPDATED", "ITEMS_AVAILABILITY_AND_PRICE_UPDATED")
STOCK_EVENTS = ("ITEMS_AVAILABILITY_UPDATED", "ITEMS_AVAILABILITY_AND_PRICE_UPDATED")
ITEM_EVENTS = PRICE_EVENTS + STOCK_EVENTS + ("ITEMS_CATALOG_UPDATED", "ITEMS_REMOVED")


def apply_item_event(event: dict, settings) -> str:
    """
    Apply one PersonalShopEvent about items. Returns a short log line.

    - price events: Item Prices (selling and buying list)
    - stock events: a Stock Reconciliation, but only when all Cloudstore stock
      lands in one ERPNext warehouse. An event quantity is a total with no
      warehouse split, so with several mapped warehouses it is left to the
      next full sync instead of being put in the wrong place.
    - catalogue events: the full item the event carries is stored like a sync
    - removed events: the stock of the Items is set to 0 in every mapped warehouse. Cloudstore
      sends this event both when an item leaves the catalogue and when its quantity is set to 0,
      and the payload does not say which, so the Item stays enabled and can be restocked.
    """
    event_type = event.get("type")
    rows = event.get("items") or []
    done, skipped = 0, 0

    if event_type == "ITEMS_CATALOG_UPDATED":
        items = [r["item"] for r in rows if r.get("item")]
        if items:
            upsert_batch(items)
        return f"{event_type}: {len(items)} item(s) stored, {len(rows) - len(items)} without item data."

    warehouse = _single_warehouse(settings) if event_type in STOCK_EVENTS else None
    stock_entries = []

    for row in rows:
        item_code = _item_code(row)
        if not item_code:
            skipped += 1
            continue
        if event_type == "ITEMS_REMOVED":
            stock_entries += [{"item_code": item_code, "warehouse": wh, "qty": 0.0} for wh in _warehouses(settings)]
        if event_type in PRICE_EVENTS:
            _apply_prices(item_code, row, settings)
        if event_type in STOCK_EVENTS and row.get("qty") is not None and warehouse:
            stock_entries.append({"item_code": item_code, "warehouse": warehouse, "qty": _non_negative(row["qty"])})
        done += 1

    stock_skipped = 0
    # ERPNext throws when a reconciliation changes nothing, so submit only real differences.
    stock_entries = _only_changed(stock_entries)
    if stock_entries:
        stock_skipped = _submit_stock_reconciliation(stock_entries)
    frappe.db.commit()

    note = ""
    if event_type in STOCK_EVENTS and not warehouse:
        note = " Stock not applied: Cloudstore stock maps to more than one warehouse, next full sync sets it."
    if stock_skipped:
        note += f" {stock_skipped} stock row(s) skipped: no valuation rate in ERPNext."
    return f"{event_type}: {done} item(s) applied, {skipped} not in ERPNext.{note}"


def _apply_prices(item_code: str, row: dict, settings):
    if row.get("sale_price") and settings.cs_price_list:
        _upsert_price(item_code, settings.cs_price_list, row["sale_price"])
    if row.get("stock_price") and settings.cs_buying_price_list:
        _upsert_price(item_code, settings.cs_buying_price_list, row["stock_price"])


def _item_code(row: dict) -> str:
    """Our Item for an event row: by SKU, else by the Cloudstore item id."""
    sku = row.get("sku")
    if sku and frappe.db.exists("Item", sku):
        return sku
    oid = (row.get("item_id") or {}).get("$oid")
    return frappe.db.get_value("Item", {"supplier_id": oid}, "name") if oid else ""


def _warehouses(settings) -> set:
    names = {r.warehouse for r in (settings.cs_warehouse_mapping or []) if r.warehouse}
    if settings.cs_sync_warehouse:
        names.add(settings.cs_sync_warehouse)
    return names


def _single_warehouse(settings):
    names = _warehouses(settings)
    return next(iter(names)) if len(names) == 1 else None
