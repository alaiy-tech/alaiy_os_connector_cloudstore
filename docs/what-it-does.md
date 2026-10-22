# What the connector does

Cloudstore is a supplier platform: catalogue, stock per warehouse, prices,
orders. The connector copies catalogue, prices and stock into ERPNext, can send
Sales Orders to Cloudstore, and reads Cloudstore events back.

Two rules hold for every feature:

- A scheduled job runs only if **Enable Cloudstore** is set and the job's
  interval is not `Disabled`. All intervals default to `Disabled`.
- The connector writes to Cloudstore only when **Send Sales Orders to
  Cloudstore** is set. No other feature writes to Cloudstore.

## Feature table

| Feature | Trigger | Direction | Reads | Writes in ERPNext | Writes to Cloudstore |
|---|---|---|---|---|---|
| Category sync | Button or schedule | In | `GET /categories/tree` | Item Group | nothing |
| Item sync | Button or schedule | In | `GET /items?withQuantities=true` | Item (template, variant), Item Price, Item Supplier, Item Supplier Attribute, Brand, Customs Tariff Number, Item Barcode, Website Slideshow, Item Attribute Value, Warehouse, Stock Reconciliation | nothing |
| Stock sync | Schedule or API call | In | `GET /items?withQuantities=true` | Stock Reconciliation, Item Supplier Attribute (3 rows) | nothing |
| Order push | Sales Order submit | Out | nothing | Sales Order tracking fields | `POST /orders` |
| Order cancel | Sales Order cancel | Out | nothing | Sales Order status field | `DELETE /orders/{id}` |
| Order status refresh | Schedule or API call | In | `GET /orders/findByShopOrderId` | Sales Order status field | nothing |
| Events | Schedule or API call | In | `GET /events` | Sales Order fields, Item Price, Stock Reconciliation, Item (`disabled`), Item (catalogue update) | nothing |
| Search and lookup | API call | In | `listBySearchTerm`, `listByCode` | nothing | nothing |
| Single-item sync | API call | In | `findByCode`, `listByParentSKUList` | same as item sync | nothing |
| Filtered sync | API call | In | `POST /v2/items/listParentsByFilter` | same as item sync | nothing |
| Category browse | API call | In | `categories/roots`, `categories/{id}/children` | nothing | nothing |

## What each feature does not do

| Feature | Does not |
|---|---|
| Category sync | Delete Item Groups that disappeared from Cloudstore. |
| Item sync | Delete or disable Items that disappeared from Cloudstore. Keep more than one Item Group per Item. Keep non-English text in Item fields. |
| Stock sync | Create or change Items. Touch items that do not exist in ERPNext. |
| Order push | Send lines of items not from Cloudstore. Retry a failed push by itself. Send later edits to a submitted Sales Order. |
| Order cancel | Run for a Sales Order that was never sent. |
| Events | Send anything. `POST /events` is sandbox only on Cloudstore and is not called. |
| Lookup and search | Save anything. |
