# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""
Stock freshness check for the Connector Health page.

A sample of items is compared with a live lookup: does the quantity ERPNext holds still match what
Cloudstore reports? A few differences are normal, because ERPNext stock moves with our own sales between
syncs. Widespread differences mean the stock sync is stale. The check names no item: its answer is shown
on the page and posted in alerts.

The decision (`judge`, `live_quantity`, `first_item`) is plain Python. `stock_freshness` is the
registered `health_method`; the page remembers its answer for half an hour, so the live lookups run a few
times an hour at most.
"""

SAMPLE_SIZE = 10
MIN_COMPARABLE = 5   # fewer comparable items than this is not enough to judge
WARN_SHARE = 0.3     # this share of the sample differing is a warning
RED_SHARE = 0.6      # and this share is red
TOLERANCE = 0.0001

KEY = "stock_freshness"
LABEL = "Stock matches Cloudstore"


def _check(state, detail):
    return {"key": KEY, "label": LABEL, "state": state, "detail": detail}


def live_quantity(item) -> float:
    """The quantity Cloudstore reports for an item. A missing item has none; an oversold (negative)
    quantity is held at 0, the same as the stock sync does."""
    if not item:
        return 0.0
    if item.get("qty") is not None:
        return max(float(item["qty"]), 0.0)
    return sum(max(float(row.get("qty") or 0), 0.0) for row in (item.get("whs") or []))


def first_item(reply, sku):
    """The item with exactly this SKU from a lookup reply (a single item or a list), else None."""
    content = reply.get("content") if isinstance(reply, dict) else reply
    items = content if isinstance(content, list) else [content] if isinstance(content, dict) else []
    return next((i for i in items if isinstance(i, dict) and i.get("sku") == sku), None)


def judge(pairs, unreadable=0):
    """The check for (ERPNext quantity, Cloudstore quantity) pairs. `unreadable` counts sampled items
    whose lookup failed, which are mentioned but not judged."""
    total = len(pairs)
    suffix = f" ({unreadable} could not be checked)" if unreadable else ""
    if total < MIN_COMPARABLE:
        return _check("unknown", f"Too few items could be compared to judge ({total}){suffix}")
    differing = sum(1 for erp, live in pairs if abs(erp - live) > TOLERANCE)
    share = differing / total
    state = "red" if share >= RED_SHARE else "warn" if share >= WARN_SHARE else "ok"
    return _check(state, f"{differing} of {total} sampled items differ from Cloudstore{suffix}")


def stock_freshness():
    """The registered health_method: sample items that carry Cloudstore stock and look each one up live."""
    import random

    import frappe

    from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient

    skus = sorted(set(frappe.get_all(
        "Item Supplier Attribute",
        filters={"connector_name": "cloudstore", "attribute_key": "cloudstore_qty"},
        pluck="parent", limit=5000,
    )))
    if not skus:
        return [_check("unknown", "No items with Cloudstore stock to sample")]
    sample = random.sample(skus, min(SAMPLE_SIZE, len(skus)))

    settings = frappe.get_single("Cloudstore Connector Settings")
    warehouses = {(settings.cs_sync_warehouse or "").strip()}
    warehouses.update((row.warehouse or "").strip() for row in (settings.get("cs_warehouse_mapping") or []))
    warehouses.discard("")

    client = CloudstoreClient()
    pairs, unreadable = [], 0
    for sku in sample:
        try:
            item = first_item(client.items.find_by_code(sku), sku)
        except RuntimeError as exc:
            if "error 404" not in str(exc):
                unreadable += 1
                continue
            item = None  # not listed any more: Cloudstore has none, which is what the stock sync zeroes
        except Exception:
            unreadable += 1
            continue
        erp = sum(
            float(row.actual_qty or 0)
            for row in frappe.get_all("Bin", filters={"item_code": sku, "warehouse": ["in", list(warehouses)]},
                                      fields=["actual_qty"])
        ) if warehouses else 0.0
        pairs.append((erp, live_quantity(item)))
    if sample and unreadable == len(sample):
        raise RuntimeError("Cloudstore could not be reached")  # the page shows the exception class only
    return [judge(pairs, unreadable)]
