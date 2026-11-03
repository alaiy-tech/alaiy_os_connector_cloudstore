# Known gaps

Behaviour that is missing or limited, as it is in the code.

## Reliability

| Area | Fact |
|---|---|
| Client | GET requests are retried up to three times (2, 5 and 10 seconds) on HTTP 429, 502, 503, 504 and on connection errors and timeouts. A `Retry-After` header is honoured up to 60 seconds. Other methods are never retried, so a create call cannot be sent twice. 401 and 403 fail at once. Rate-limit headers are not logged. Timeout is 20 seconds for every call. |
| Scheduler | After a failed run the next try waits at least five minutes, or the interval if longer. A run is treated as still running for 120 minutes; an older `running` log is marked failed. |
| Order push | The orders job retries pushes that failed for a transient reason (network error, HTTP 429 or 5xx) for 2 days after the Sales Order date. A rejection by Cloudstore (HTTP 4xx) is not retried; fix the cause and call `push_sales_order`. A failed cancel is not retried. Retries need **Order Status Refresh Interval** to be set. |
| Settings page | `trigger_categories_sync` and `trigger_items_sync` have no role check. |

## Order push

| Area | Fact |
|---|---|
| Quantity | `qty` is sent as an integer; a fractional quantity is cut. |
| Date | `order_dt` is the Sales Order creation time written with a trailing `Z`, with no timezone conversion. |
| Tax | `unit_price_tax_incl` is the net rate times grand total over net total of the whole Sales Order. A Sales Order mixing taxes gives approximate values for the Cloudstore lines. |
| Edits | Changes to a submitted Sales Order are not sent. Cancel and re-submit (amend) sends a new order. |
| Status | The connector never sends PATCH or PUT. Status changes come from Cloudstore only. |
| Options | The create call's `partial_order`, `selected_whs` and the `X-API-Feature` header are not used. |
| Names | The Sales Order name is the Cloudstore `shop_order_id`. |

## Items and stock

| Area | Fact |
|---|---|
| Removal | Items that disappear from Cloudstore stay in ERPNext during the item sync. Only the `ITEMS_REMOVED` event disables Items. |
| Item Group | One Item Group per Item (the first category). All category ids are kept in the `category_ids` attribute. |
| Language | Item name and description use English, or the first language present. Other languages are not kept. |
| Price 0 | A price of 0 is skipped, so an existing price stays. |
| Item sync stock | The item sync reconciles every item on every run, even when the quantity did not change. The stock-only sync reconciles changed quantities only. |
| Overwrite | A reconciliation replaces the ERPNext quantity with the Cloudstore quantity. |
| Sold out | The Cloudstore item list holds only items that are in stock. After a complete read, the stock sync sets ERPNext stock to 0 for Cloudstore items that still have stock but are no longer listed. It skips this when the list is under half the size of the last good run, or when it would zero more than half of the stocked items. An item counts as a Cloudstore item when it has the supplier link or a price in the connector's buying price list. The item sync does not zero anything. |
| Valuation | Each reconciliation row carries the item's valuation rate, else the warehouse rate. A row with neither is skipped and counted; the run is then marked `failed` with the count. A warehouse rate that differs from the item's rate counts as a change, so the row is re-valued. |
| Cost | `sale_price` is written to the optional **Cost Price List**. Nothing in the connector reads that list; the client app sets item valuation from it. |
| Failed reconciliation | Insert and submit run in a savepoint, so a failure leaves no draft document. |
| Warehouses | An unmapped Cloudstore warehouse id is mapped to the default warehouse until someone changes the row. |
| Volume | An item has about 30 Item Supplier Attribute rows on the template and on each variant. |
| Customer prices | `customerId` is never sent, so customer-specific prices are not read. |

## Events

| Area | Fact |
|---|---|
| Consumption | Reading `GET /events` is assumed to consume events. Raw events are written to the log for that reason. |
| Stock events | Applied only when all Cloudstore stock maps to one ERPNext warehouse. |
| Push | No stock or price push exists. `POST /events` is sandbox only. |
| Unknown types | Event types outside the seven known ones are logged and not applied. |

## Not implemented

- Inventory catalog import (`/inventory-catalog/*`): the endpoint methods
  exist, nothing calls them, and the file format Cloudstore expects is not
  documented in the spec.
- `GET /ping`, `GET /categories`, `GET /categories/{id}`, `GET /items/{id}`,
  `GET /orders/listByFilter`, `GET /orders/{id}`, `PUT /orders/{id}`,
  `PATCH /orders/{id}`: no feature calls them.
- Delivery Note, Shipment or invoice creation from Cloudstore data.
