# Events

Code: `cloudstore/sync_events.py`, `cloudstore/item_events.py`,
`sync_orders.apply_order_event`. Trigger: scheduler (`cs_events_sync_interval`)
or `api.sync.trigger_events_sync` (System Manager or Stock Manager).

Cloudstore describes `GET /events` as "Get next events page". It takes no paging
or type parameters, so a page that has been read is treated as consumed. The
job writes every event it reads to the log, whether it could apply it or not.

`POST /events` exists in Cloudstore only in the sandbox; production answers 403.
The connector does not call it.

## Run: `sync_events.run(trigger)`

1. Creates the log (`sync_type=events`).
2. `read_events`: calls `GET /events` repeatedly, collecting `content[]`. It
   stops at an empty page, when a page starts with the same event `_id` as the
   previous page (the server is not moving forward), or after 20 pages.
3. For each event, `apply_event` inside a try block. An exception is logged as
   `ERROR <type>: <message>`, counted, and written to Error Log.
4. Log counts: `items_processed` = events read, `items_failed` = events that
   raised, `items_updated` = the rest.
5. `log_messages` = one result line per event, then one `EVENT <json>` line
   per raw event.
6. `status=failed` when any event raised, else `success`.

## Event types

| Type | Effect | Result line |
|---|---|---|
| `ORDER_STATUS_UPDATED` | `cs_order_status` = `new_status` on the matching Sales Order | `applied to Sales Order` or `no matching Sales Order` |
| `SHIPMENT_UPSERTED` | `cs_carrier`, `cs_tracking_number`, `cs_tracking_url`, `cs_shipment_status` on the matching Sales Order | same |
| `ITEMS_PRICE_UPDATED` | Item Prices | see below |
| `ITEMS_AVAILABILITY_UPDATED` | Stock Reconciliation | see below |
| `ITEMS_AVAILABILITY_AND_PRICE_UPDATED` | both of the above | see below |
| `ITEMS_CATALOG_UPDATED` | catalogue update of the item | see below |
| `ITEMS_REMOVED` | Items disabled | see below |
| any other type | nothing | `type not handled` |

### Matching a Sales Order: `apply_order_event`

1. The event's `shop_order_id` is looked up as a Sales Order name (the connector
   sends the Sales Order name as `shop_order_id`).
2. Otherwise each `shipment.orders[].order_id.$oid` is looked up in
   `Sales Order.cs_order_id`.
3. No match: nothing is written and the line is `no matching Sales Order`. This
   is not counted as a failure.

Fields written: `new_status` when present; for a shipment: `carrier`,
`tracking_number`, `tracking_url`, and the status of the last entry of
`status_history` (shipment statuses `SHIPPED`, `PARTIALLY_SHIPPED`, `ONGOING`,
`DELIVERED`).

### Item events: `item_events.apply_item_event`

Each event carries `items[]` of `{item_id, sku, qty, stock_price, sale_price,
item}`. The ERPNext Item is found by `sku`, else by `item_id.$oid` matched to
`Item.supplier_id`. Rows without an Item are counted as not in ERPNext and
skipped.

| Type | What is written |
|---|---|
| price types | `sale_price` to the Selling Price List and `stock_price` to the Buying Price List, each only when the value is above 0 and the list is set |
| stock types | one Stock Reconciliation with `qty` per row on the single warehouse, only when all Cloudstore stock maps to one ERPNext warehouse (the Warehouse Mapping targets plus the Default Sync Warehouse form exactly one name). With more than one warehouse nothing is written and the line says: `Stock not applied: Cloudstore stock maps to more than one warehouse, next full sync sets it.` An event quantity is a total with no warehouse split. |
| `ITEMS_CATALOG_UPDATED` | rows with an `item` object are stored through `upsert_batch` like an item sync; rows without are reported as `without item data` |
| `ITEMS_REMOVED` | `Item.disabled` = 1 for each row, with `frappe.db.set_value` (no hooks) |

Result line: `<type>: <n> item(s) applied, <n> not in ERPNext.` The applied count
is the number of rows that matched an Item.
