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
        attr_cache = {}  # Item Attribute name -> set of already-registered values, this run

        stats = {"processed": 0, "created": 0, "updated": 0, "failed": 0}
        stock_batch = []  # collect (item_code, qty) tuples across all pages

        for content, metadata in client.get_paginated(
            "/items", params={"withQuantities": "true"}
        ):
            if log.pages_total == 0:
                log.pages_total = int(metadata.get("total_pages", 0))

            for item_data in content:
                try:
                    action, stock_entry = _upsert_item(item_data, settings, attr_cache)
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
            try:
                _submit_stock_reconciliation(stock_batch, warehouse)
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

    `cache` (Item Attribute name -> set of known values) is populated lazily
    per sync run to avoid re-querying the same attribute for every item.
    """
    if not value:
        return
    known = cache.get(attribute_name)
    if known is None:
        known = set(frappe.get_all(
            "Item Attribute Value",
            filters={"parent": attribute_name},
            pluck="attribute_value",
        ))
        cache[attribute_name] = known
    if value in known:
        return
    attr = frappe.get_doc("Item Attribute", attribute_name)
    attr.append("item_attribute_values", {"attribute_value": value, "abbr": value})
    attr.save(ignore_permissions=True)
    known.add(value)


# ---------------------------------------------------------------------------
# Per-item upsert
# ---------------------------------------------------------------------------


def _upsert_item(item_data: dict, settings, attr_cache: dict) -> tuple:
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
    apparel_size = (props.get("apparel_size") or props.get("size") or "").strip()
    mnf_color = (props.get("mnf_color") or "").strip()
    hs_code = (props.get("hs_code") or "").strip()
    made_in_code = (props.get("made_in_code") or "").strip()
    country_of_origin = _iso_to_country_name(made_in_code)
    sale_price = item_data.get("sale_price") or 0.0
    buy_price = props.get("buy_price") or 0.0
    qty = float(item_data.get("qty") or 0)

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
        template.hs_code = hs_code
    if country_of_origin:
        template.country_of_origin = country_of_origin

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
        variant.hs_code = hs_code
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
    company = frappe.defaults.get_global_default("company")
    expense_account = (
        frappe.get_cached_value("Company", company, "stock_adjustment_account") or ""
        if company else ""
    )
    recon = frappe.new_doc("Stock Reconciliation")
    recon.purpose = "Stock Reconciliation"
    recon.company = company
    if expense_account:
        recon.expense_account = expense_account
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


_ISO2_TO_COUNTRY = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AR": "Argentina",
    "AU": "Australia", "AT": "Austria", "AZ": "Azerbaijan", "BE": "Belgium",
    "BD": "Bangladesh", "BR": "Brazil", "BG": "Bulgaria", "KH": "Cambodia",
    "CA": "Canada", "CL": "Chile", "CN": "China", "CO": "Colombia",
    "HR": "Croatia", "CZ": "Czech Republic", "DK": "Denmark", "EG": "Egypt",
    "EE": "Estonia", "ET": "Ethiopia", "FI": "Finland", "FR": "France",
    "GE": "Georgia", "DE": "Germany", "GH": "Ghana", "GR": "Greece",
    "HK": "Hong Kong", "HU": "Hungary", "IN": "India", "ID": "Indonesia",
    "IR": "Iran", "IQ": "Iraq", "IE": "Ireland", "IL": "Israel",
    "IT": "Italy", "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan",
    "KE": "Kenya", "KR": "South Korea", "KW": "Kuwait", "LV": "Latvia",
    "LB": "Lebanon", "LT": "Lithuania", "MY": "Malaysia", "MX": "Mexico",
    "MA": "Morocco", "NL": "Netherlands", "NZ": "New Zealand", "NG": "Nigeria",
    "NO": "Norway", "PK": "Pakistan", "PE": "Peru", "PH": "Philippines",
    "PL": "Poland", "PT": "Portugal", "QA": "Qatar", "RO": "Romania",
    "RU": "Russia", "SA": "Saudi Arabia", "SG": "Singapore", "SK": "Slovakia",
    "ZA": "South Africa", "ES": "Spain", "LK": "Sri Lanka", "SE": "Sweden",
    "CH": "Switzerland", "TW": "Taiwan", "TH": "Thailand", "TN": "Tunisia",
    "TR": "Turkey", "UA": "Ukraine", "AE": "United Arab Emirates",
    "GB": "United Kingdom", "US": "United States", "UY": "Uruguay",
    "UZ": "Uzbekistan", "VN": "Vietnam", "YE": "Yemen",
}


def _iso_to_country_name(code: str) -> str:
    """Map a 2-letter ISO country code to an ERPNext Country name. Returns '' if unknown."""
    if not code:
        return ""
    return _ISO2_TO_COUNTRY.get(code.upper().strip(), "")


def _append_log(log, message: str):
    """Append a line to log.log_messages without saving."""
    existing = log.log_messages or ""
    log.log_messages = (existing + "\n" + message).strip()
