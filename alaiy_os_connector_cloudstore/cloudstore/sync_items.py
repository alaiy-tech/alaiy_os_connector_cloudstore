# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime

from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


STALE_RUNNING_THRESHOLD_MINUTES = 120


def _has_active_items_sync() -> bool:
    """
    True if another items sync is genuinely still in flight. A "running" log
    older than the stale threshold is treated as orphaned — e.g. its worker
    was killed mid-run by a deploy/restart — and is marked failed so it stops
    permanently blocking future runs.
    """
    cutoff = frappe.utils.add_to_date(now_datetime(), minutes=-STALE_RUNNING_THRESHOLD_MINUTES)
    running = frappe.get_all(
        "Cloudstore Sync Log",
        filters={"sync_type": "items", "status": "running"},
        fields=["name", "started_at"],
    )
    active = False
    for row in running:
        if row.started_at and row.started_at < cutoff:
            frappe.db.set_value("Cloudstore Sync Log", row.name, {
                "status": "failed",
                "finished_at": now_datetime(),
                "error_message": "Marked failed: orphaned running log (worker likely restarted mid-run).",
            })
        else:
            active = True
    if running:
        frappe.db.commit()
    return active


def run(trigger: str = "scheduled") -> str:
    """
    Synchronise Cloudstore items (templates + variants) into ERPNext Items.

    Pages through /items, upserts each item as a template + variant, creates
    Item Prices, links Suppliers, writes extended attributes, then submits one
    batched Stock Reconciliation covering all synced variants.

    Skips entirely (logged as "skipped") if another items sync is still
    running — a full sync can take longer than the configured schedule
    interval, and running two at once causes DB lock contention between
    them rather than either finishing faster.

    Returns:
        The name (ID) of the Cloudstore Sync Log document.
    """
    if _has_active_items_sync():
        log = frappe.new_doc("Cloudstore Sync Log")
        log.sync_type = "items"
        log.trigger = trigger
        log.status = "skipped"
        log.started_at = now_datetime()
        log.finished_at = now_datetime()
        log.error_message = "Skipped: another items sync is already running."
        log.insert(ignore_permissions=True)
        frappe.db.commit()
        return log.name

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
        attr_cache = {}  # Item Attribute name -> set of already-registered values, this run

        default_warehouse = _ensure_warehouse((settings.cs_sync_warehouse or "").strip())
        # Cloudstore warehouse ID (whs[].wh_id) -> ERPNext Warehouse name, seeded
        # from the settings' own mapping table and extended as new IDs are seen.
        wh_cache = {row.cs_wh_id: row.warehouse for row in (settings.cs_warehouse_mapping or [])}

        stats = {"processed": 0, "created": 0, "updated": 0, "failed": 0}
        stock_batch = []  # collect {"item_code", "warehouse", "qty"} dicts across all pages

        for content, metadata in client.get_paginated(
            "/items", params={"withQuantities": "true"}
        ):
            if log.pages_total == 0:
                log.pages_total = int(metadata.get("total_pages", 0))

            for item_data in content:
                try:
                    action, stock_entries = _upsert_item(
                        item_data, settings, attr_cache, wh_cache, default_warehouse
                    )
                    stats["processed"] += 1
                    if action == "created":
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1
                    if stock_entries:
                        stock_batch.extend(stock_entries)
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
        # one per variant. Each entry already carries its own resolved warehouse.
        if stock_batch:
            try:
                _submit_stock_reconciliation(stock_batch)
            except Exception as exc:
                _append_log(log, f"WARNING: Stock Reconciliation failed: {exc}")
                frappe.log_error(
                    title="Cloudstore: stock reconciliation failed",
                    message=frappe.get_traceback(),
                )

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
        "alaiy_os_connector_cloudstore.cloudstore.sync_items.run",
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

    if not frappe.db.exists("Custom Field", "Item-slideshow"):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Item",
            "fieldname": "slideshow",
            "label": "Slideshow",
            "fieldtype": "Link",
            "options": "Website Slideshow",
            "insert_after": "image",
        }).insert(ignore_permissions=True)

    frappe.db.commit()


def _ensure_attribute_value(attribute_name: str, value: str, cache: dict):
    """
    Register `value` as a valid Item Attribute Value for `attribute_name` if
    it isn't already. ERPNext validates variant attribute values against this
    list in a code path that `Item.flags.ignore_validate` does not bypass, so
    values must be registered up front or every variant save fails with
    "Attribute Value X is not valid for the selected attribute Y".

    Deliberately does NOT set ignore_validate on the Item Attribute doc:
    ItemAttribute.validate() resets frappe.flags.attribute_values to None as
    a side effect, which forces erpnext.controllers.item_variant's
    process-lifetime cache of valid attribute values to re-fetch from the DB
    on the next variant save. Skipping validate() here would leave that
    cache stale for the rest of the sync run, so every value registered
    after the first cache fill would still fail validation despite already
    being committed to the DB.

    The abbreviation must also be unique (case-insensitively) across the
    whole attribute, independent of the value itself — e.g. pre-existing
    seed data has "Large" abbreviated "L", so a Cloudstore size that's
    literally the string "L" collides on abbr even though the value itself
    is new. Disambiguate the abbr on collision rather than the value.

    `cache` (Item Attribute name -> {"values": set, "abbrs": set}) is
    populated lazily per sync run to avoid re-querying for every item.
    """
    if not value:
        return
    state = cache.get(attribute_name)
    if state is None:
        rows = frappe.get_all(
            "Item Attribute Value",
            filters={"parent": attribute_name},
            fields=["attribute_value", "abbr"],
        )
        state = {
            "values": {r.attribute_value for r in rows},
            "abbrs": {(r.abbr or "").lower() for r in rows},
        }
        cache[attribute_name] = state
    if value in state["values"]:
        return

    abbr = value
    suffix = 2
    while abbr.lower() in state["abbrs"]:
        abbr = f"{value}-{suffix}"
        suffix += 1

    attr = frappe.get_doc("Item Attribute", attribute_name)
    attr.append("item_attribute_values", {"attribute_value": value, "abbr": abbr})
    attr.save(ignore_permissions=True)
    state["values"].add(value)
    state["abbrs"].add(abbr.lower())


# ---------------------------------------------------------------------------
# Per-item upsert
# ---------------------------------------------------------------------------


def _upsert_item(item_data: dict, settings, attr_cache: dict, wh_cache: dict, default_warehouse: str) -> tuple:
    """
    Create or update an ERPNext Item template and its variant from one
    Cloudstore item payload.

    Template item_code = "{sku_parent}__{mnf_color_code}"
    Variant  item_code = sku (the full SKU from Cloudstore)

    Returns:
        ("created" | "updated", [{"item_code": str, "warehouse": str, "qty": float}, ...])
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
    apparel_size = (props.get("apparel_size") or props.get("size") or "").strip()
    mnf_color = (props.get("mnf_color") or "").strip()
    hs_code = (props.get("hs_code") or "").strip()
    mnf_barcode = (props.get("mnf_barcode") or "").strip()
    made_in_code = (props.get("made_in_code") or "").strip()
    country_of_origin = _iso_to_country_name(made_in_code)
    sale_price = item_data.get("sale_price") or 0.0
    # Buying cost comes from the top-level "stock_price" field, not props.buy_price.
    buy_price = item_data.get("stock_price") or 0.0

    # Template groups all variants sharing the same sku_parent + color colorway
    mnf_color_code = (props.get("mnf_color_code") or "DEFAULT").strip()
    template_code = f"{sku_parent}__{mnf_color_code}"

    imgs = sorted(item_data.get("imgs") or [], key=lambda x: x.get("pos", 99))
    image_url = imgs[0].get("url", "") if imgs else ""
    extra_image_urls = [i.get("url") for i in imgs[1:] if i.get("url")]

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
    template.sku_parent = sku_parent
    template.mnf_color_code = mnf_color_code
    if mnf_color:
        template.manufacturer_color = mnf_color
    if hs_code:
        template.customs_tariff_number = _ensure_customs_tariff_number(hs_code)
    if country_of_origin:
        template.country_of_origin = country_of_origin

    # Template declares both Size and Color as the variant dimensions.
    # Color is fixed per template (one template = one colorway); Size varies.
    _ensure_template_attribute(template, "Size")
    _ensure_template_attribute(template, "Color")

    # Bypass ERPNext's attribute-value pre-defined list check — we manage
    # data from an external source.
    template.flags.ignore_validate = True
    # Item.on_update() (not gated by ignore_validate, which only skips
    # validate()) calls update_variants(), which re-saves every existing
    # variant of this template WITHOUT ignore_validate, using whatever data
    # each variant currently holds in the DB. Since this sync updates each
    # variant's own attributes directly and doesn't want ERPNext's
    # template-to-variant attribute copy, skip it entirely — without this,
    # saving a template mid-run could re-trigger full validation against a
    # sibling variant this run hasn't reached yet.
    template.flags.dont_update_variants = True
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
        # Purge orphaned child rows left by any previous raw-SQL deletion
        for _tbl in ("tabItem Variant Attribute", "tabUOM Conversion Detail"):
            frappe.db.sql(f"DELETE FROM `{_tbl}` WHERE parent=%s", sku)
    else:
        variant = frappe.get_doc("Item", sku)

    variant.variant_of = template_code
    variant.item_name = title
    variant.item_group = item_group or "All Item Groups"
    if brand:
        variant.brand = brand
    if image_url:
        variant.image = image_url
    variant.supplier_id = item_id_oid
    variant.sku_parent = sku_parent
    variant.last_synced_at = now_datetime()
    if mnf_color:
        variant.manufacturer_color = mnf_color
    if hs_code:
        variant.customs_tariff_number = _ensure_customs_tariff_number(hs_code)
    if country_of_origin:
        variant.country_of_origin = country_of_origin

    size_val = (apparel_size or "N/A").strip().upper()
    _ensure_attribute_value("Size", size_val, attr_cache)

    # Only Size is the varying dimension on variants; Color lives on the template.
    variant.set("attributes", [])
    variant.append("attributes", {"attribute": "Size", "attribute_value": size_val})

    existing_uoms = [row.uom for row in (variant.uoms or [])]
    if variant.stock_uom not in existing_uoms:
        variant.append("uoms", {"uom": variant.stock_uom, "conversion_factor": 1.0})

    if mnf_barcode:
        _ensure_barcode(variant, mnf_barcode)

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

    # Slideshow for additional images (linked to template)
    if extra_image_urls:
        _upsert_slideshow(template_code, image_url, extra_image_urls)

    # Stock entries returned to caller for batched reconciliation — one per
    # Cloudstore warehouse row, each resolved to its mapped ERPNext Warehouse.
    stock_entries = (
        _build_stock_entries(sku, item_data, settings, wh_cache, default_warehouse)
        if sku else []
    )

    return ("created" if variant_is_new else "updated"), stock_entries


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


def _resolve_warehouse_for_wh_id(wh_id: str, settings, cache: dict, default_warehouse: str) -> str:
    """
    Map a Cloudstore warehouse ID (whs[].wh_id) to its ERPNext Warehouse via
    the connector's own Warehouse Mapping table. The first time a given
    wh_id is seen, it's auto-added to that table pointed at the default
    warehouse, so it becomes visible in Settings for re-pointing later
    instead of silently pooling into the default forever.
    """
    if not wh_id:
        return default_warehouse
    if wh_id in cache:
        return _ensure_warehouse(cache[wh_id]) or default_warehouse

    settings.append("cs_warehouse_mapping", {"cs_wh_id": wh_id, "warehouse": default_warehouse})
    settings.save(ignore_permissions=True)
    frappe.db.commit()
    cache[wh_id] = default_warehouse
    return default_warehouse


def _build_stock_entries(sku: str, item_data: dict, settings, wh_cache: dict, default_warehouse: str) -> list:
    """
    One stock entry per Cloudstore warehouse row (whs[]), each resolved to
    its mapped ERPNext Warehouse. Falls back to a single entry against the
    default warehouse using the item's top-level qty if Cloudstore didn't
    report a whs[] breakdown for this item.
    """
    whs = item_data.get("whs") or []
    if not whs:
        return [{
            "item_code": sku,
            "warehouse": default_warehouse,
            "qty": float(item_data.get("qty") or 0),
        }]

    entries = []
    for row in whs:
        wh_id = ((row.get("wh_id") or {}).get("$oid") or "").strip()
        warehouse = _resolve_warehouse_for_wh_id(wh_id, settings, wh_cache, default_warehouse)
        entries.append({
            "item_code": sku,
            "warehouse": warehouse,
            "qty": float(row.get("qty") or 0),
        })
    return entries


def _submit_stock_reconciliation(entries: list):
    """
    Submit one Stock Reconciliation covering all synced variants — each
    entry already carries its own resolved warehouse.

    When a warehouse/item combination has no prior Stock Ledger Entry,
    ERPNext treats the reconciliation as an Opening Entry and requires an
    Asset/Liability-type difference account, rejecting the normal P&L
    Stock Adjustment account. Since we can't tell in advance which items
    are "opening" for a brand-new warehouse, try the normal account first
    and fall back to the company's Temporary Opening account on that
    specific validation error.
    """
    entries = [e for e in entries if e.get("warehouse")]
    if not entries:
        return
    company = frappe.defaults.get_global_default("company")

    def _build_recon(expense_account):
        recon = frappe.new_doc("Stock Reconciliation")
        recon.purpose = "Stock Reconciliation"
        recon.company = company
        if expense_account:
            recon.expense_account = expense_account
        for entry in entries:
            recon.append("items", {
                "item_code": entry["item_code"],
                "warehouse": entry["warehouse"],
                "qty":       entry["qty"],
            })
        recon.flags.ignore_permissions = True
        return recon

    stock_adjustment_account = (
        frappe.get_cached_value("Company", company, "stock_adjustment_account") or ""
        if company else ""
    )
    try:
        recon = _build_recon(stock_adjustment_account)
        recon.insert()
        recon.submit()
    except frappe.ValidationError as exc:
        if "Opening Entry" not in str(exc):
            raise
        opening_account = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Temporary", "is_group": 0}, "name"
        )
        if not opening_account:
            raise
        recon = _build_recon(opening_account)
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
        {"supplier_id": first_oid},
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


def _ensure_customs_tariff_number(hs_code: str) -> str:
    """
    Item.customs_tariff_number is a Link to Customs Tariff Number (autonamed
    from its own tariff_number field), not a plain text field — create the
    record if this HS code hasn't been seen before, then return its name to
    link against.
    """
    if not frappe.db.exists("Customs Tariff Number", hs_code):
        frappe.get_doc({
            "doctype": "Customs Tariff Number",
            "tariff_number": hs_code,
        }).insert(ignore_permissions=True)
    return hs_code


def _ensure_barcode(variant, barcode: str):
    """
    Add `barcode` to the variant's Barcodes table if not already there.
    Item Barcode's own `barcode` field is globally unique, so a value
    already claimed by a *different* item is skipped rather than raising —
    a data quality issue upstream shouldn't fail the whole item sync.
    """
    existing = [row.barcode for row in (variant.barcodes or [])]
    if barcode in existing:
        return
    owner = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
    if owner and owner != variant.item_code:
        return
    variant.append("barcodes", {"barcode": barcode})


def _upsert_slideshow(item_code: str, primary_url: str, extra_urls: list):
    """
    Create or update a Website Slideshow linked to the Item template.
    All images (primary + extra) go in as Slideshow Items ordered by position.
    """
    slideshow_name = f"CS-{item_code}"[:140]
    all_urls = ([primary_url] if primary_url else []) + extra_urls

    if frappe.db.exists("Website Slideshow", slideshow_name):
        ss = frappe.get_doc("Website Slideshow", slideshow_name)
        ss.set("slideshow_items", [])
    else:
        ss = frappe.new_doc("Website Slideshow")
        ss.slideshow_name = slideshow_name

    for idx, url in enumerate(all_urls, start=1):
        ss.append("slideshow_items", {"image": url, "heading": "", "idx": idx})

    ss.flags.ignore_validate = True
    if ss.is_new():
        ss.insert(ignore_permissions=True)
    else:
        ss.save(ignore_permissions=True)

    # Link slideshow to the template item
    frappe.db.set_value("Item", item_code, "slideshow", slideshow_name)


def _iso_to_country_name(code: str) -> str:
    """
    Map a 2-letter ISO country code to an ERPNext Country name via the
    Country doctype's own `code` field, rather than a hand-maintained name
    table — ERPNext's own country names drift from common usage (e.g.
    "Türkiye", not "Turkey") and a hardcoded list silently goes stale.
    Returns '' if unknown.
    """
    if not code:
        return ""
    return frappe.db.get_value("Country", {"code": code.lower().strip()}, "name") or ""


def _append_log(log, message: str):
    """Append a line to log.log_messages without saving."""
    existing = log.log_messages or ""
    log.log_messages = (existing + "\n" + message).strip()
