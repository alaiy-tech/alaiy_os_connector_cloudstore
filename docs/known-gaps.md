# Known gaps

Behaviour that is missing or limited, as it is in the code.

## Reliability

| Area | Fact |
|---|---|
| Client | No retry, no backoff, no handling of HTTP 429. One failed request fails the call. Timeout is 20 seconds for every call. |
| Scheduler | A failed run is due again on the next minute tick. Only successful runs delay the next one. |
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
| Valuation | Stock Reconciliation rows carry no valuation rate. |
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
