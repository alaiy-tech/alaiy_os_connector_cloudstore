# Items

Code: `cloudstore/sync_items.py`, `cloudstore/item_attributes.py`. Trigger:
**Sync Items** button (`api.sync.trigger_items_sync`) or the scheduler.

## Run: `sync_items.run(trigger)`

1. If another items run is active (`running` log younger than 120 minutes),
   writes a log with `status=skipped` and returns.
2. Creates the log (`sync_type=items`, `status=running`).
3. `_ensure_item_attributes`: creates, if missing, Item Attributes `Size` and
   `Color`, UOM `Nos`, Item Group `All Item Groups`, and the Item custom field
   `slideshow`.
4. Creates the Default Sync Warehouse if it does not exist, under
   `All Warehouses - <company abbr>`.
5. Loads the Warehouse Mapping into a dict (`cs_wh_id` to warehouse).
6. Writes a WARNING line to the log for each of Supplier, Selling Price List,
   Buying Price List that is empty.
7. Loops over `client.items.paginated()` (`GET /items?withQuantities=true`,
   page size from settings). For each item it calls `_upsert_item` inside a
   try block. An exception is logged as `ERROR sku=<sku>: <message>`, counted in
   `items_failed`, written to Error Log, and the loop continues.
8. After each page: updates `pages_done`, `items_processed`, `items_created`,
   `items_updated`, `items_failed`, saves the log, commits.
9. After the last page: one Stock Reconciliation for all collected stock
   entries (see [stock.md](stock.md)).
10. `status=success`, or `failed` with `error_message` when the reconciliation
    failed ("Items synced but stock was not updated: ...") or any other
    exception was raised. `finished_at` is set in all cases.

`items_created` counts new variants, `items_updated` existing variants.

## `_upsert_item(item_data, settings, attr_cache, wh_cache, default_warehouse)`

Input: one item object from `/items`. Returns `("created" | "updated",
stock_entries)`.

### Values derived from the payload

| Variable | Source |
|---|---|
| `sku` | `sku` |
| `sku_parent` | `props.sku_parent`, else `sku` |
| `title` | `locs.singles.title.en`, else the first language present, else `sku_parent` |
| `description` | `locs.singles.desc` the same way, else empty |
| `brand` | `props.brand` |
| `size` | `props.apparel_size`, else `props.size`; uppercased; `N/A` if both are empty |
| `mnf_color` | `props.mnf_color` |
| `mnf_color_code` | `props.mnf_color_code`, else `DEFAULT` |
| `template_code` | `<sku_parent>__<mnf_color_code>` |
| `sale_price` | `sale_price` |
| `buy_price` | `stock_price` (not `props.buy_price`) |
| `image_url` | `url` of the `imgs[]` entry with the lowest `pos` |
| `extra_image_urls` | `url` of the other `imgs[]`, in `pos` order |
| Item Group | `cats[0].$oid` matched to `Item Group.supplier_id`, else `All Item Groups` |
| Country of origin | `props.made_in_code` matched to `Country.code` (lowercase) |

### Step 1: template Item (`template_code`)

Created if missing, otherwise updated. One template per parent SKU and colour.

| Item field | Value |
|---|---|
| `has_variants` | 1 |
| `stock_uom` | `Nos` (new only) |
| `item_name` | title |
| `description` | description, only when not empty |
| `item_group` | resolved Item Group |
| `brand` | brand; the Brand is created if missing |
| `image` | `image_url` |
| `sku_parent`, `mnf_color_code` | as derived |
| `manufacturer_color` | `mnf_color`, when not empty |
| `customs_tariff_number` | `props.hs_code`; the Customs Tariff Number is created if missing |
| `country_of_origin` | resolved country |
| attributes | rows `Size` and `Color` |

Saved with `ignore_validate` and `dont_update_variants` set, so ERPNext does not
re-save sibling variants.

### Step 2: variant Item (`sku`)

| Item field | Value |
|---|---|
| `variant_of` | `template_code` |
| `stock_uom` | `Nos` (new only) |
| `item_name`, `description`, `item_group`, `brand`, `image` | same as template |
| `supplier_id` | `item_id.$oid` |
| `sku_parent`, `manufacturer_color`, `customs_tariff_number`, `country_of_origin` | same as template |
| `last_synced_at` | time of the sync |
| attributes | one row: `Size` = size. The value is added to the Size attribute first if missing. |
| `uoms` | row `Nos`, factor 1 |
| `barcodes` | `props.mnf_barcode`, `props.ean`, `props.barcode`, each `barcodes[].code`, duplicates removed |

A barcode already used by a different Item is skipped without an error. For a
new variant, leftover child rows from earlier deletions (`Item Variant
Attribute`, `UOM Conversion Detail`) are deleted first. Saved with
`ignore_validate`.

### Step 3: prices

Item Price on the variant (`sku`), created or updated:

| Price List | Value | Condition |
|---|---|---|
| Selling Price List | `sale_price` | list set and value above 0 |
| Buying Price List | `stock_price` | list set and value above 0 |

### Step 4: supplier rows

Only when **Supplier** is set:

- Item Supplier row on the variant with supplier part number `sku`, and on the
  template with `sku_parent`.
- Item Supplier Attribute rows on both the template and the variant, from
  `item_attributes.build_supplier_attributes`. Existing rows of this supplier
  with connector name `cloudstore` are replaced, except the three stock rows
  (`cloudstore_qty`, `cloudstore_stock`, `cloudstore_stock_at`) owned by the
  stock sync.

### Step 5: slideshow

When the item has more than one image, Website Slideshow `CS-<template_code>`
(140 characters at most) is created or rebuilt with all images in order and
linked in the template's `slideshow` field.

### Step 6: stock entries

Returned to the caller (see [stock.md](stock.md)).

## Item Supplier Attribute rows

Built by `build_supplier_attributes(item_data, mnf_color_code)`. Rows with an
empty value are not stored. Every value is text.

| Key | Source |
|---|---|
| every key of `props` | the same key and value (`brand`, `size`, `apparel_size`, `ean`, `barcode`, `mnf_barcode`, `mnf_code`, `mnf_material_code`, `mnf_color`, `hs_code`, `made_in_code`, `season`, `season_short`, `collection`, `age`, `po`, `size_grid`, `size_grid_name`, `interlem_description`, `buy_price`, `sku_parent`, and any key Cloudstore adds) |
| `mnf_color_code` | derived value (`DEFAULT` when missing) |
| `title_en`, `desc_en` | English title and description |
| `color_en`, `made_en`, `sex_en`, `care_en`, `size_conversion_en` | English text of `locs.singles.*` |
| `composition` | `composition[]` as `<perc>% <material>`, joined by `, `; a part other than `GENERAL` is appended in brackets |
| `materials` | `locs.lists.materials[]`, English, joined by `, ` |
| `category_ids` | all `cats[].$oid`, joined by `, ` |
| `source_updated_at` | `lst_info_update_dt.$date` |
| `image_placement` | JSON of `pos`, `placement`, `excluded_shops` for images that have either |
| `shops_reservation` | JSON of warehouse reservations, only when some exist |
| `abs`, `bc`, `linked_items`, `external_identifiers`, `search_tags`, `pb` | JSON text, only when Cloudstore sends them |

## Helper behaviour

| Function | Behaviour |
|---|---|
| `_ensure_attribute_value` | Registers a Size value in the Item Attribute before use, because ERPNext validates variant values against that list. The abbreviation is made unique case-insensitively (`-2`, `-3`, ...). Values are cached per run. |
| `_upsert_price` | Updates `price_list_rate` of the existing Item Price for item and list, else inserts one. |
| `_upsert_item_supplier` | Adds or updates the Item Supplier row; no-op when the Supplier does not exist. |
| `_upsert_supplier_attributes` | Skipped when the DocType Item Supplier Attribute does not exist. |
| `_ensure_brand`, `_ensure_customs_tariff_number` | Create the record when missing. |
| `_iso_to_country_name` | Country lookup through `Country.code`; empty when unknown. |
| `_ensure_barcode` | Skips a barcode owned by another Item. |

## `upsert_batch(items)`

Stores a given list of item objects with the same logic, for the on-demand
features. Per item: `_upsert_item` in a try block and a commit. The stock
reconciliation runs once at the end and raises on failure after the items are
saved. Returns `processed`, `created`, `updated`, `failed`, `errors[]`.
