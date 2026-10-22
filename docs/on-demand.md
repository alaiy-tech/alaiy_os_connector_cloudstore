# On-demand tools

Whitelisted Frappe methods. Call them from the console, a script, or
`/api/method/<dotted path>`. Lists can be passed as a JSON array
(`["A","B"]`) or comma-separated text (`A,B`).

## `api/sync.py`

Path prefix: `alaiy_os_connector_cloudstore.api.sync.`

| Method | Roles | Does |
|---|---|---|
| `trigger_categories_sync()` | any logged-in user | Queues `sync_categories.run` on `long`. Returns `{queued: true}`. |
| `trigger_items_sync()` | any logged-in user | Queues `sync_items.run`. |
| `trigger_stock_sync()` | System Manager, Stock Manager | Queues `sync_stock.run`. |
| `trigger_events_sync()` | System Manager, Stock Manager | Queues `sync_events.run`. |
| `trigger_orders_sync()` | System Manager, Sales Manager | Queues `sync_orders.run` (status refresh). |
| `push_sales_order(sales_order)` | System Manager, Sales Manager | Runs `push_order` now. Use it to retry a failed push. |
| `get_sync_status(sync_type)` | any logged-in user | Last 3 Cloudstore Sync Log rows of that type: name, status, started_at, finished_at, the four counts, pages_total, pages_done, error_message. |
| `lookup_item(sku=None, parent_sku=None)` | System Manager, Stock Manager | Returns the raw Cloudstore reply. `parent_sku` uses `listByParentSKUList`, `sku` uses `findByCode`. Saves nothing. |

## `api/lookup.py`

Path prefix: `alaiy_os_connector_cloudstore.api.lookup.` Roles: System Manager,
Stock Manager.

| Method | Arguments | Does |
|---|---|---|
| `search_items` | `term` | `GET /items/listBySearchTerm`, 50 results. Matches SKU, barcode, title, description, brand, season. Saves nothing. |
| `find_items` | `code`, `partial=0`, `code_type="SKU"` | `GET /items/listByCode`, first 50 results. `partial=0` sends `_searchType=EXACT`, `partial=1` sends `PARTIAL_CASE_INSENSITIVE`. `code_type`: `SKU`, `SKU_PARENT`, `BARCODE`, `BARCODES`, `EAN`, `ITEM_ID`, `MNF_CODE`, `MPN`, `NS_INTERNAL_ID`, `UPC`. Saves nothing. |
| `sync_skus` | `skus` | `findByCode` per SKU. Keeps replies whose `sku` equals the requested one. Stores them with `upsert_batch`. |
| `sync_parents` | `parent_skus` | `POST /items/listByParentSKUList`, stores every size returned with `upsert_batch`. |
| `sync_filtered` | `brands`, `category_ids`, `warehouse_ids` | `POST /v2/items/listParentsByFilter` page by page (50 parents per page, at most 500 parents), stores the `items` of each parent with `upsert_batch`. |
| `browse_categories` | `parent_id=None` | Root categories, or the children of `parent_id`; first 100. Returns `[{id, name, leaf, parent_id}]`. |

`search_items` and `find_items` return rows
`{sku, sku_parent, title, brand, qty, sale_price, stock_price, exists_in_erp}`.
`exists_in_erp` is true when an Item with that SKU exists.

`sync_skus`, `sync_parents` and `sync_filtered` return `processed`, `created`,
`updated`, `failed`, `errors[]`, plus `requested` (`sync_skus`, `sync_parents`)
or `parents` (`sync_filtered`). They raise "Cloudstore returned no matching
items." or "No products match this filter." when nothing is found.

Stock: `findByCode` and `listByParentSKUList` have no `withQuantities`
parameter. When a reply carries neither `qty` nor `whs`, stock of that item is
left unchanged. `sync_filtered` requests quantities.

Filter body (`sync_filtered`), from the Cloudstore spec: `brands`
`{values: [text], op}`, `cat_ids` `{values: [{$oid}], op}`, `whs_ids`
`{values: [{$oid}], op}`. The connector always sends `op: "IN"`. Brands match
case-sensitively. A category includes its subcategories. All given conditions
must hold. At least one of the three lists is required.
