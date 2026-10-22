# Setup

The app installs disabled. Saving the settings form with **Enable Cloudstore**
turned on for the first time provisions the custom fields and defaults below.

## Prerequisites

- Frappe bench with `alaiy_os` and `erpnext`.
- A Cloudstore shop account: API base URL and Bearer token.
- The API URL must end in the version, for example `https://host/shop/v1`.
  Endpoint paths are appended to it. The v2 filter call builds its URL by
  replacing the first `/v1` in the configured URL with `/v2`, so the URL must
  contain `/v1`.

## Settings: Cloudstore Connector Settings

Single DocType. Permission: System Manager only. Module: Alaiy OS Connector
Cloudstore.

| Section | Fieldname | Label | Type | Default | Required | Used by |
|---|---|---|---|---|---|---|
| | `is_enabled` | Enable Cloudstore | Check | 0 | | Scheduler (`check_and_enqueue` returns at once when off), first-enable setup, registry flag |
| API Connection | `cs_api_url` | API URL | Data | | yes | `CloudstoreClient` |
| | `cs_bearer_token` | Bearer Token | Password | | yes | `CloudstoreClient` (`Authorization: Bearer`) |
| Sync Defaults | `cs_supplier` | Supplier | Link Supplier | | yes | Item Supplier rows, Item Supplier Attribute rows |
| | `cs_sync_warehouse` | Default Sync Warehouse | Link Warehouse | | yes | Warehouse for unmapped Cloudstore warehouse IDs |
| | `cs_warehouse_mapping` | Warehouse Mapping | Table | | | Cloudstore warehouse ID to ERPNext Warehouse |
| | `cs_buying_price_list` | Buying Price List | Link Price List | | yes | Receives `stock_price` |
| | `cs_price_list` | Selling Price List | Link Price List | | yes | Receives `sale_price` |
| Sync Schedule | `cs_page_size` | Page Size | Int | 250 | yes | Items per `/items` request. Cloudstore maximum is 250. |
| | `cs_category_sync_interval` | Category Sync Interval | Select | Disabled | yes | `Disabled`, `1 min`, `5 min`, `10 min`, `30 min` |
| | `cs_items_sync_interval` | Items Sync Interval | Select | Disabled | yes | same options |
| | `cs_stock_sync_interval` | Stock Sync Interval | Select | Disabled | | same options |
| | `cs_orders_sync_interval` | Order Status Refresh Interval | Select | Disabled | | `Disabled`, `5 min`, `10 min`, `30 min` |
| Orders | `cs_push_orders` | Send Sales Orders to Cloudstore | Check | 0 | | Submit and cancel hooks |
| | `cs_order_push_status` | Status When Sent | Select | PENDING | | `PENDING` or `CONFIRMED`, the status the order is created with |
| Events | `cs_events_sync_interval` | Events Interval | Select | Disabled | | `Disabled`, `5 min`, `10 min`, `30 min` |

Child table **Cloudstore Warehouse Mapping**: `cs_wh_id` (Data, required,
Cloudstore's `whs[].wh_id.$oid`) and `warehouse` (Link Warehouse, required).

Buttons on the form (Actions menu): **Test Connection**, **Sync Category
Tree**, **Sync Items**. Stock, order and event runs have no button; start them
with the API calls in [on-demand.md](on-demand.md).

**Test Connection** calls `alaiy_os.api.connectors.test_connector` for
connector id `cloudstore`, which runs
`api/test_connection.py::test_connection`. That function issues
`GET {api_url}/categories/tree` with a 10 second timeout and returns:

| Result | Message |
|---|---|
| HTTP 200 | success |
| HTTP 401 | token rejected |
| HTTP 403 | access forbidden |
| other status | `HTTP <code>: <first 200 chars of body>` |
| connection error | could not connect to the URL |
| timeout | timed out after 10 seconds |
| URL or token empty | the matching "not set" message |

## Other DocTypes

**Cloudstore Sync Log** — one row per run. See [architecture.md](architecture.md).

## What first enable creates

`CloudstoreConnectorSettings.validate` calls `_run_setup` when `is_enabled`
changes from 0 to 1. It runs `setup/install.py`:

| Function | Creates (only if missing) |
|---|---|
| `setup_custom_fields` | Item Group: `supplier_id`, `supplier_cat_level`. Item: `supplier_id`, `sku_parent`, `mnf_color_code`, `last_synced_at`, `manufacturer_color`, `hs_code`. |
| `setup_order_fields` | Sales Order: `cs_order_id`, `cs_order_status`, `cs_push_error`, `cs_carrier`, `cs_tracking_number`, `cs_tracking_url`, `cs_shipment_status`. All read only and editable after submit. |
| `setup_item_attributes` | Item Attributes `Size` and `Color` |
| `create_default_supplier` | A Supplier for Cloudstore (name set in the function) in Supplier Group `International Brands` |
| `create_default_price_lists` | Price Lists `Cloudstore - Buying` (buying) and `Cloudstore - Selling` (selling), currency INR |

These defaults are only created. The sync uses the Supplier and Price Lists
chosen in the settings fields.

The first item sync also creates, if missing: UOM `Nos`, Item Group
`All Item Groups`, and the Item custom field `slideshow` (Link to Website
Slideshow, after `image`).

## After install and migrate

`hooks.py` runs `setup.install.after_install` on install (clears the stored
token field) and `setup.install.sync_connector_registry` on every migrate:

- forces the settings DocType to be a Single,
- sets `is_enabled` on sites that already had the Item `supplier_id` field,
- adds the Sales Order fields when the connector is already enabled,
- upserts the row `cloudstore` in OS Connector Registry from
  `connector_meta.py` (registry fields `connection_status` and
  `last_tested_at` are left alone),
- refreshes the Alaiy OS sidebar entries, including the **Cloudstore Logs**
  link to Cloudstore Sync Log.

## Disable

Setting `is_enabled` to 0 stops every scheduled job and the Sales Order submit
and cancel hooks. Nothing is removed.
