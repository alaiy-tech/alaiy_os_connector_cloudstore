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
    Synchronise Cloudstore items (templates + variants) into ERPNext Items.

    Creates a Cloudstore Sync Log, pages through /items, upserts each item
    as a template + variant, creates/updates Item Prices, then marks the log.

    Returns:
        The name (ID) of the Cloudstore Sync Log document.
    """
    log = frappe.new_doc("Cloudstore Sync Log")
    log.sync_type = "items"
    log.trigger = trigger
    log.status = "running"
    log.started_at = now_datetime()
    log.items_processed = 0
    log.items_created = 0
    log.items_updated = 0
    log.items_failed = 0
    log.pages_total = 0
    log.pages_done = 0
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        settings = frappe.get_single("Cloudstore Connector Settings")
        client = CloudstoreClient()

        _ensure_item_attributes()

        stats = {"processed": 0, "created": 0, "updated": 0, "failed": 0}

        for content, metadata in client.get_paginated(
            "/items", params={"withQuantities": "true"}
        ):
            # Set total pages on first page
            if log.pages_total == 0:
                log.pages_total = int(metadata.get("total_pages", 0))

            for item_data in content:
                try:
                    result = _upsert_item(item_data, settings)
                    stats["processed"] += 1
                    if result == "created":
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1
                except Exception as exc:
                    sku = item_data.get("sku", "unknown")
                    stats["failed"] += 1
                    _append_log(log, f"ERROR sku={sku}: {exc}")
                    frappe.log_error(
                        title=f"Cloudstore item sync error: {sku}",
                        message=frappe.get_traceback(),
                    )

            log.pages_done += 1
            log.items_processed = stats["processed"]
            log.items_created = stats["created"]
            log.items_updated = stats["updated"]
            log.items_failed = stats["failed"]
            log.save(ignore_permissions=True)
            frappe.db.commit()

        log.status = "success"

    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)[:1000]
        frappe.log_error(
            title="Cloudstore items sync failed",
            message=frappe.get_traceback(),
        )

    finally:
        log.finished_at = now_datetime()
        log.save(ignore_permissions=True)
        frappe.db.commit()

    return log.name


def run_in_background(trigger: str = "manual") -> dict:
    """
    Enqueue an items sync job on the long queue and return immediately.

    Returns:
        {"queued": True}
    """
    frappe.enqueue(
        "alaiy_os_cloudstore_connector.cloudstore.sync_items.run",
        queue="long",
        trigger=trigger,
    )
    return {"queued": True}


# ---------------------------------------------------------------------------
# Attribute bootstrap
# ---------------------------------------------------------------------------


def _ensure_item_attributes():
    """
    Make sure the "Size" and "Color" Item Attributes exist in ERPNext.
    Creates them (with numeric_values=0) if absent.
    """
    for attr_name in ("Size", "Color"):
        if not frappe.db.exists("Item Attribute", attr_name):
            attr = frappe.new_doc("Item Attribute")
            attr.attribute_name = attr_name
            attr.numeric_values = 0
            attr.insert(ignore_permissions=True)

    # Ensure the "Nos" UOM exists (mandatory on every ERPNext Item)
    if not frappe.db.exists("UOM", "Nos"):
        uom = frappe.new_doc("UOM")
        uom.uom_name = "Nos"
        uom.insert(ignore_permissions=True)

    # Ensure a root Item Group exists as fallback
    if not frappe.db.exists("Item Group", "All Item Groups"):
        root = frappe.new_doc("Item Group")
        root.item_group_name = "All Item Groups"
        root.is_group = 1
        root.insert(ignore_permissions=True)

    frappe.db.commit()


# ---------------------------------------------------------------------------
# Per-item upsert
# ---------------------------------------------------------------------------


def _upsert_item(item_data: dict, settings) -> str:
    """
    Create or update an ERPNext Item template and its variant from one
    Cloudstore item payload.

    Args:
        item_data: One element from the Cloudstore /items content list.
        settings:  Cloudstore Connector Settings single doc.

    Returns:
        "created" if the variant was newly inserted, "updated" otherwise.
    """
    # ------------------------------------------------------------------
    # Extract fields
    # ------------------------------------------------------------------
    sku = (item_data.get("sku") or "").strip()
    props = item_data.get("props") or {}
    locs = item_data.get("locs") or {}
    singles = locs.get("singles") or {}

    sku_parent = (props.get("sku_parent") or sku).strip()
    item_id_oid = (item_data.get("item_id") or {}).get("$oid") or ""

    # Localised text — prefer English
    title = _pick_locale(singles.get("title"), fallback=sku_parent)
    description = _pick_locale(singles.get("desc"), fallback="")
    color = _pick_locale(singles.get("color"), fallback="")

    brand = (props.get("brand") or "").strip()
    apparel_size = (props.get("apparel_size") or "").strip()
    sale_price = item_data.get("sale_price") or 0.0
    buy_price = props.get("buy_price") or 0.0

    # Primary image
    imgs = item_data.get("imgs") or []
    image_url = ""
    if imgs:
        first = sorted(imgs, key=lambda x: x.get("pos", 99))[0]
        image_url = first.get("url") or ""

    # Item Group from first category OID
    cats = item_data.get("cats") or []
    item_group = _resolve_item_group(cats)

    # ------------------------------------------------------------------
    # 1. Template item (has_variants=1)
    # ------------------------------------------------------------------
    if frappe.db.exists("Item", sku_parent):
        template = frappe.get_doc("Item", sku_parent)
        template_is_new = False
    else:
        template = frappe.new_doc("Item")
        template.item_code = sku_parent
        template.has_variants = 1
        template.stock_uom = "Nos"
        template_is_new = True

    template.item_name = title
    if description:
        template.description = description
    template.item_group = item_group or "All Item Groups"
    if brand:
        template.brand = brand
    if image_url:
        template.image = image_url
    template.cs_cloudstore_source = "cloudstore"
    template.cs_parent_sku = sku_parent
    if brand:
        _ensure_brand(brand)

    # Declare Size and Color attributes on the template
    _ensure_template_attribute(template, "Size")
    _ensure_template_attribute(template, "Color")

    # Skip ERPNext's variant attribute validation — we manage data from an
    # external source and don't need the attribute values pre-defined in the
    # Item Attribute table.
    template.flags.ignore_validate = True
    if template_is_new:
        template.insert(ignore_permissions=True)
    else:
        template.save(ignore_permissions=True)

    # ------------------------------------------------------------------
    # 2. Variant item
    # ------------------------------------------------------------------
    variant_is_new = not frappe.db.exists("Item", sku)

    if variant_is_new:
        variant = frappe.new_doc("Item")
        variant.item_code = sku
        variant.stock_uom = "Nos"
    else:
        variant = frappe.get_doc("Item", sku)

    variant.variant_of = sku_parent
    variant.item_name = title
    variant.item_group = item_group or "All Item Groups"
    if brand:
        variant.brand = brand
    if image_url:
        variant.image = image_url
    variant.cs_cloudstore_id = item_id_oid
    variant.cs_parent_sku = sku_parent
    variant.cs_cloudstore_source = "cloudstore"
    variant.cs_last_synced_at = now_datetime()

    # Normalize casing: uppercase for sizes (M, L, XL, 36…), title for colors
    size_val = (apparel_size or "N/A").strip().upper()
    color_val = (color or "N/A").strip().title()

    variant.set("attributes", [])
    variant.append("attributes", {"attribute": "Size",  "attribute_value": size_val})
    variant.append("attributes", {"attribute": "Color", "attribute_value": color_val})

    # ERPNext before_save checks that stock_uom appears in the uoms conversion
    # table even when ignore_validate=True.  Ensure it's present.
    existing_uoms = [row.uom for row in (variant.uoms or [])]
    if variant.stock_uom not in existing_uoms:
        variant.append("uoms", {"uom": variant.stock_uom, "conversion_factor": 1.0})

    # Bypass ERPNext's attribute value pre-defined list validation.
    # The Size/Color ItemAttribute DocTypes exist; their values table is
    # managed separately and does not need to cover every value we import.
    variant.flags.ignore_validate = True
    if variant_is_new:
        variant.insert(ignore_permissions=True)
    else:
        variant.save(ignore_permissions=True)

    # ------------------------------------------------------------------
    # 3. Item Price
    # ------------------------------------------------------------------
    price_list = (settings.cs_price_list or "").strip()
    if price_list and sku:
        existing_price = frappe.db.get_value(
            "Item Price",
            {"item_code": sku, "price_list": price_list},
            "name",
        )
        if existing_price:
            price_doc = frappe.get_doc("Item Price", existing_price)
            price_doc.price_list_rate = sale_price
            price_doc.save(ignore_permissions=True)
        else:
            price_doc = frappe.new_doc("Item Price")
            price_doc.item_code = sku
            price_doc.price_list = price_list
            price_doc.price_list_rate = sale_price
            price_doc.insert(ignore_permissions=True)

    return "created" if variant_is_new else "updated"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _ensure_brand(brand_name: str):
    """Create a Brand record if it doesn't exist yet."""
    if not brand_name:
        return
    if not frappe.db.exists("Brand", brand_name):
        b = frappe.new_doc("Brand")
        b.brand = brand_name
        b.insert(ignore_permissions=True)
        frappe.db.commit()


def _pick_locale(locale_dict, fallback: str = "") -> str:
    """Return the English value from a {lang: value} dict, or any first value."""
    if not locale_dict:
        return fallback
    return locale_dict.get("en") or next(iter(locale_dict.values()), fallback) or fallback


def _resolve_item_group(cats: list) -> str:
    """
    Look up the ERPNext Item Group name for the first category OID in cats.
    Returns empty string if not found.
    """
    if not cats:
        return ""
    first_oid = (cats[0] or {}).get("$oid") or ""
    if not first_oid:
        return ""
    name = frappe.db.get_value(
        "Item Group",
        {"cs_cloudstore_id": first_oid},
        "name",
    )
    return name or ""


def _ensure_template_attribute(template, attribute_name: str):
    """
    Add an attribute row to the template's attributes child table if absent.
    Safe to call on both new and existing docs.
    """
    existing = [row.attribute for row in (template.attributes or [])]
    if attribute_name not in existing:
        template.append("attributes", {"attribute": attribute_name})


def _append_log(log, message: str):
    """Append a line to log.log_messages without saving."""
    existing = log.log_messages or ""
    log.log_messages = (existing + "\n" + message).strip()
