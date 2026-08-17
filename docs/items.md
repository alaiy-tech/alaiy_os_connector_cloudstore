# Items

Cloudstore's item catalogue (with per-warehouse quantities) syncs one-way
into ERPNext Items, Item Prices, and Stock Reconciliation. Code:
`cloudstore/sync_items.py`, triggered by `sync_jobs.check_and_enqueue`
(scheduled) or `api.sync.trigger_items_sync` (manual button).

---

## Cloudstore field → Alaiy OS field

| Cloudstore (`/items` payload) | Alaiy OS |
|---|---|
| `sku` | Variant `item_code`; also `variant.supplier_part_no` via Item Supplier row |
| `props.sku_parent` (fallback: `sku`) | `sku_parent` (custom field, template + variant) |
| `props.mnf_color_code` (fallback: `DEFAULT`) | `mnf_color_code` (custom field); template key = `{sku_parent}__{mnf_color_code}` |
| `locs.singles.title` (locale dict, `en` preferred) | `item_name` (template + variant) |
| `locs.singles.desc` | `description` (template only) |
| `props.brand` | `brand` (creates Brand record if new) |
| `props.apparel_size` / `props.size` | Variant `Size` attribute value (upper-cased, `N/A` if blank) |
| `props.mnf_color` | `manufacturer_color` (custom field) |
| `props.hs_code` | `customs_tariff_number` (Link; record auto-created) |
| `props.mnf_barcode` | Item Barcode row (skipped if already claimed by a different item) |
| `props.made_in_code` (ISO-2) | `country_of_origin` (resolved via ERPNext's own Country `code` field) |
| `sale_price` | Item Price in `cs_price_list` (selling) |
| `stock_price` (top-level, **not** `props.buy_price`) | Item Price in `cs_buying_price_list` (buying) |
| `imgs[]` (sorted by `pos`) | first → `image`; rest → Website Slideshow `CS-{template_code}` |
| `cats[0].$oid` | `item_group` (looked up via the category's `supplier_id`; falls back to `All Item Groups`) |
| `item_id.$oid` | `supplier_id` (custom field, variant only) |
| `whs[].wh_id.$oid` + `whs[].qty` | Stock Reconciliation entries, warehouse resolved via `cs_warehouse_mapping` (falls back to top-level `qty` against the default warehouse if `whs[]` is absent) |
| `props.season`, `season_short`, `collection`, `age`, `hs_code`, `made_in_code`, `po`, `size_grid`, title/desc | Item Supplier Attribute rows (`connector_name = "cloudstore"`) on the template |

## Template / variant model

One template Item (`has_variants=1`) per `sku_parent + mnf_color_code`
combination — i.e. one template per colorway. `Size` and `Color` are both
declared as template variant attributes, but only `Size` actually varies
across the template's variants; `Color` is fixed per template. Every variant
save uses `ignore_validate` to bypass ERPNext's variant-attribute
pre-registration check (attribute values are registered separately via
`_ensure_attribute_value` first) and `dont_update_variants` on the template
to stop ERPNext's own `update_variants()` from re-touching sibling variants
mid-run.

## Stock

Quantities are **not** written per item as they're processed. Every page's
warehouse/qty rows are collected into one in-memory batch across the whole
run, and a single Stock Reconciliation is submitted at the end covering
every variant synced in that run. If the normal Stock Adjustment account is
rejected because a warehouse/item pair has no prior ledger entry (an
"Opening Entry" per ERPNext), the code retries once with the company's
Temporary Opening account. If the whole run fails after this point (or the
process is killed) with items already upserted but stock not yet
reconciled, no stock reconciliation is submitted for that run at all — this
is a real gap, not by design.

## Known gaps

- **No retry on failed API calls** (see architecture.md) — a single
  transient failure fails the whole page/run.
- **No delete/deactivate handling** — an item removed from Cloudstore is
  never removed or disabled in ERPNext.
- **No change detection** — every field is unconditionally overwritten every
  run; there's no hash/version check to skip unchanged items.
- **Concurrency guard is coarse**: only one items sync at a time is allowed
  (others are logged `skipped`), and a `running` log is only considered
  stale after 2 hours — a genuinely slow but still-alive run within that
  window blocks everything else.
