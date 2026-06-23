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

    Pages through /items, upserts each item as a template + variant, creates
    Item Prices, links Suppliers, writes extended attributes, then submits one
    batched Stock Reconciliation covering all synced variants.

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
        stock_batch = []  # collect (item_code, qty) tuples across all pages

        for content, metadata in client.get_paginated(
            "/items", params={"withQuantities": "true"}
        ):
            if log.pages_total == 0:
                log.pages_total = int(metadata.get("total_pages", 0))

            for item_data in content:
                try:
                    action, stock_entry = _upsert_item(item_data, settings)
                    stats["processed"] += 1
                    if action == "created":
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1
                    if stock_entry:
                        stock_batch.append(stock_entry)
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

        # One Stock Reconciliation for all synced variants — far cheaper than
        # one per variant.
        warehouse = _ensure_warehouse((settings.cs_sync_warehouse or "").strip())
        if stock_batch and warehouse:
            _submit_stock_reconciliation(stock_batch, warehouse)

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

    if not frappe.db.exists("UOM", "Nos"):
        uom = frappe.new_doc("UOM")
        uom.uom_name = "Nos"
        uom.insert(ignore_permissions=True)

    if not frappe.db.exists("Item Group", "All Item Groups"):
        root = frappe.new_doc("Item Group")
        root.item_group_name = "All Item Groups"
        root.is_group = 1
        root.insert(ignore_permissions=True)

    frappe.db.commit()


# ---------------------------------------------------------------------------
# Per-item upsert
# ---------------------------------------------------------------------------


def _upsert_item(item_data: dict, settings) -> tuple:
    """
    Create or update an ERPNext Item template and its variant from one
    Cloudstore item payload.

    Template item_code = "{sku_parent}__{mnf_color_code}"
    Variant  item_code = sku (the full SKU from Cloudstore)

    Returns:
        ("created" | "updated", {"item_code": str, "qty": float} | None)
    """
    sku = (item_data.get("sku") or "").strip()
    props = item_data.get("props") or {}
    locs = item_data.get("locs") or {}
    singles = locs.get("singles") or {}

    sku_parent = (props.get("sku_parent") or sku).strip()
    item_id_oid = (item_data.get("item_id") or {}).get("$oid") or ""

    title = _pick_locale(singles.get("title"), fallback=sku_parent)
    description = _pick_locale(singles.get("desc"), fallback="")

    brand = (props.get("brand") or "").strip()
    apparel_size = (props.get("apparel_size") or "").strip()
    sale_price = item_data.get("sale_price") or 0.0
    buy_price = props.get("buy_price") or 0.0
    qty = float(item_data.get("qty") or 0)

    # Template groups all variants sharing the same sku_parent + color colorway
    mnf_color_code = (props.get("mnf_color_code") or "DEFAULT").strip()
    template_code = f"{sku_parent}__{mnf_color_code}"

    imgs = item_data.get("imgs") or []
    image_url = ""
    if imgs:
        first = sorted(imgs, key=lambda x: x.get("pos", 99))[0]
        image_url = first.get("url") or ""

    cats = item_data.get("cats") or []
    item_group = _resolve_item_group(cats)

    # ------------------------------------------------------------------
    # 1. Template item (has_variants=1)
    #    Groups all size variants of the same colour + parent SKU.
    # ------------------------------------------------------------------
    if frappe.db.exists("Item", template_code):
        template = frappe.get_doc("Item", template_code)
        template_is_new = False
    else:
        template = frappe.new_doc("Item")
        template.item_code = template_code
        template.has_variants = 1
        template.stock_uom = "Nos"
        template_is_new = True

    template.item_name = title
    if description:
        template.description = description
    template.item_group = item_group or "All Item Groups"
    if brand:
        template.brand = brand
        _ensure_brand(brand)
    if image_url:
        template.image = image_url
    template.cs_sku_parent = sku_parent
    template.cs_mnf_color_code = mnf_color_code

    # Template declares both Size and Color as the variant dimensions.
    # Color is fixed per template (one template = one colorway); Size varies.
    _ensure_template_attribute(template, "Size")
    _ensure_template_attribute(template, "Color")

    # Bypass ERPNext's attribute-value pre-defined list check — we manage
    # data from an external source.
    template.flags.ignore_validate = True
    if template_is_new:
        template.insert(ignore_permissions=True)
    else:
        template.save(ignore_permissions=True)

    # ------------------------------------------------------------------
    # 2. Variant item — only Size varies across variants of one template
    # ------------------------------------------------------------------
    variant_is_new = not frappe.db.exists("Item", sku)

    if variant_is_new:
        variant = frappe.new_doc("Item")
        variant.item_code = sku
        variant.stock_uom = "Nos"
    else:
        variant = frappe.get_doc("Item", sku)

    variant.variant_of = template_code
    variant.item_name = title
    variant.item_group = item_group or "All Item Groups"
    if brand:
        variant.brand = brand
    if image_url:
        variant.image = image_url
    variant.cs_cloudstore_id = item_id_oid
    variant.cs_sku_parent = sku_parent
    variant.cs_last_synced_at = now_datetime()

    size_val = (apparel_size or "N/A").strip().upper()

    # Only Size is the varying dimension on variants; Color lives on the template.
    variant.set("attributes", [])
    variant.append("attributes", {"attribute": "Size", "attribute_value": size_val})

    existing_uoms = [row.uom for row in (variant.uoms or [])]
    if variant.stock_uom not in existing_uoms:
        variant.append("uoms", {"uom": variant.stock_uom, "conversion_factor": 1.0})

    variant.flags.ignore_validate = True
    if variant_is_new:
        variant.insert(ignore_permissions=True)
    else:
        variant.save(ignore_permissions=True)

    # ------------------------------------------------------------------
    # 3. Item Prices
    # ------------------------------------------------------------------
    selling_price_list = (settings.cs_price_list or "").strip()
    if selling_price_list and sku and sale_price:
        _upsert_price(sku, selling_price_list, sale_price)

    buying_price_list = (settings.cs_buying_price_list or "").strip()
    if buying_price_list and sku and buy_price:
        _upsert_price(sku, buying_price_list, buy_price)

    # ------------------------------------------------------------------
    # 4. Item Supplier linkage + extended attributes
    # ------------------------------------------------------------------
    supplier = (settings.cs_supplier or "").strip()
    if supplier:
        _upsert_item_supplier(sku, supplier, sku)
        _upsert_item_supplier(template_code, supplier, sku_parent)

        attrs = {
            "mnf_color":      props.get("mnf_color", ""),
            "mnf_color_code": mnf_color_code,
            "season":         props.get("season", ""),
            "season_short":   props.get("season_short", ""),
            "collection":     props.get("collection", ""),
            "age":            props.get("age", ""),
            "hs_code":        props.get("hs_code", ""),
            "made_in_code":   props.get("made_in_code", ""),
            "po":             props.get("po", ""),
            "size_grid":      props.get("size_grid", ""),
            "title_en":       _pick_locale(singles.get("title")),
            "desc_en":        _pick_locale(singles.get("desc")),
        }
        _upsert_supplier_attributes(template_code, supplier, attrs)

    # Stock entry returned to caller for batched reconciliation
    stock_entry = {"item_code": sku, "qty": qty} if sku else None

    return ("created" if variant_is_new else "updated"), stock_entry


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------


def _upsert_price(item_code: str, price_list: str, rate: float):
    """Create or update an Item Price record."""
    existing = frappe.db.get_value(
        "Item Price",
        {"item_code": item_code, "price_list": price_list},
        "name",
    )
    if existing:
        price_doc = frappe.get_doc("Item Price", existing)
        price_doc.price_list_rate = rate
        price_doc.save(ignore_permissions=True)
    else:
        price_doc = frappe.new_doc("Item Price")
        price_doc.item_code = item_code
        price_doc.price_list = price_list
        price_doc.price_list_rate = rate
        price_doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Supplier linkage helpers
# ---------------------------------------------------------------------------


def _upsert_item_supplier(item_code: str, supplier: str, supplier_part_no: str):
    """Ensure the item has a Supplier row in its supplier_items child table."""
    if not supplier or not frappe.db.exists("Supplier", supplier):
        return
    item = frappe.get_doc("Item", item_code)
    existing = [r for r in (item.supplier_items or []) if r.supplier == supplier]
    if existing:
        existing[0].supplier_part_no = supplier_part_no
    else:
        item.append("supplier_items", {
            "supplier": supplier,
            "supplier_part_no": supplier_part_no,
        })
    item.flags.ignore_validate = True
    item.save(ignore_permissions=True)


def _upsert_supplier_attributes(item_code: str, supplier: str, attrs: dict):
    """Write supplier-specific key-value attributes to Item Supplier Attribute child table."""
    if not supplier or not frappe.db.exists("DocType", "Item Supplier Attribute"):
        return
    item = frappe.get_doc("Item", item_code)
    # Replace existing rows for this connector so we don't accumulate duplicates
    item.set("supplier_attributes", [
        r for r in (getattr(item, "supplier_attributes", None) or [])
        if not (r.supplier == supplier and r.connector_name == "cloudstore")
    ])
    for key, value in attrs.items():
        if value:
            item.append("supplier_attributes", {
                "supplier": supplier,
                "connector_name": "cloudstore",
                "attribute_key": key,
                "attribute_value": str(value),
            })
    item.flags.ignore_validate = True
    item.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Warehouse + Stock Reconciliation helpers
# ---------------------------------------------------------------------------


def _ensure_warehouse(warehouse_name: str) -> str:
    """Return warehouse_name, creating the Warehouse record if it doesn't exist."""
    if not warehouse_name:
        return ""
    if frappe.db.exists("Warehouse", warehouse_name):
        return warehouse_name
    company = frappe.defaults.get_global_default("company")
    abbr = frappe.get_cached_value("Company", company, "abbr") if company else ""
    wh = frappe.new_doc("Warehouse")
    wh.warehouse_name = warehouse_name
    wh.company = company
    if abbr:
        wh.parent_warehouse = f"All Warehouses - {abbr}"
    wh.insert(ignore_permissions=True)
    frappe.db.commit()
    return wh.name


def _submit_stock_reconciliation(entries: list, warehouse: str):
    """Submit one Stock Reconciliation covering all synced variants."""
    if not entries or not warehouse:
        return
    recon = frappe.new_doc("Stock Reconciliation")
    recon.purpose = "Stock Reconciliation"
    recon.company = frappe.defaults.get_global_default("company")
    for entry in entries:
        recon.append("items", {
            "item_code": entry["item_code"],
            "warehouse": warehouse,
            "qty":       entry["qty"],
        })
    recon.flags.ignore_permissions = True
    recon.insert()
    recon.submit()
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Misc private helpers
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
