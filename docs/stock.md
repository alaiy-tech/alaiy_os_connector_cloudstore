# Stock

Cloudstore has no stock-only endpoint. Quantities arrive on item calls as
`qty` (total) and `whs[]` (per warehouse: `wh_id.$oid`, `qty`,
`shops_reservation`). Only `GET /items` and `POST /v2/items/listParentsByFilter`
take `withQuantities`.

## Warehouse resolution

`_build_stock_entries(sku, item_data, settings, wh_cache, default_warehouse)`
returns one entry `{item_code, warehouse, qty}` per element of `whs[]`:

- `whs[].wh_id.$oid` is looked up in the Warehouse Mapping.
- An id with no mapping row: a row `{cs_wh_id, warehouse = Default Sync
  Warehouse}` is added to the settings, the settings are saved and committed,
  and the default warehouse is used. The row can be re-pointed later.
- A mapped warehouse that does not exist in ERPNext is created
  (`_ensure_warehouse`).
- No `whs[]` on the item: one entry on the default warehouse with the item's
  top-level `qty` (0 when missing).
- Neither `whs` nor `qty` in the payload: no entry. Stock is left unchanged.
  This is the case for replies of calls that do not return quantities.

## Setting ERPNext stock: `_submit_stock_reconciliation(entries)`

- One Stock Reconciliation, purpose `Stock Reconciliation`, company = the
  global default company, one row per entry with `item_code`, `warehouse`,
  `qty` and `valuation_rate`.
- The valuation rate is the item's own `valuation_rate`, else the rate held in
  that warehouse. An entry with neither is skipped. The function returns the
  number of skipped entries, and the stock, item and event paths log it. The
  stock and item runs end `failed` when it is not zero.
- Insert and submit run in a savepoint: if either step fails the insert is
  undone and no draft is left.
- `expense_account` is the company's `stock_adjustment_account`.
- If ERPNext rejects it with an error containing `Opening Entry` (no earlier
  stock ledger entry for an item and warehouse), it is rebuilt with the
  company's account of type `Temporary` and submitted again. If no such
  account exists, the original error is raised.
- Entries without a warehouse are dropped.

The reconciliation sets the stock to the Cloudstore quantity. Stock changes made
in ERPNext since the last run (sales, receipts) are overwritten.

## In the item sync

`sync_items.run` collects entries of all items and submits them at the end in
reconciliations of 200 rows each (one document for a whole catalogue exceeds
the number of writes Frappe allows in one transaction). Only rows whose quantity
or valuation rate changed are submitted. If a chunk fails the run gets
`status=failed` and the log line `ERROR: Stock Reconciliation failed: ...`;
items already saved stay saved.

Rules for every reconciliation, from any caller:

- Rows for a disabled Item are left out, because ERPNext rejects them.
- A negative quantity from Cloudstore is held at 0.
- When ERPNext reports that no row would change stock or value, the call
  returns without error: the stock already matches.

## Stock-only sync: `cloudstore/sync_stock.py`

Trigger: scheduler (`cs_stock_sync_interval`) or `api.sync.trigger_stock_sync`.
It never creates or edits Items.

`run(trigger)`:

1. Creates the log (`sync_type=stock`).
2. For each page of `client.items.paginated()`, reads which of the SKUs exist as
   Items. SKUs without an Item are counted as `unknown` and skipped.
3. For an existing Item:
   - builds the stock entries as above,
   - if **Supplier** is set, stores Cloudstore's numbers (below),
   - keeps only entries whose quantity differs from `Bin.actual_qty` of that
     item and warehouse (no Bin counts as 0), or whose `Bin.valuation_rate`
     differs from the item's valuation rate. Entries without a warehouse are
     skipped.
4. After each page: saves `pages_done`, `items_processed` (items seen),
   `items_updated` (items with a changed quantity), `items_failed`, commits.
   A failing item is logged as `ERROR sku=<sku>: ...` and counted.
5. After the last page, adds an entry with quantity 0 for each Cloudstore item that
   still has stock in the sync warehouses but was not in the list (sold out; see
   known-gaps.md for the safety rules), then submits the changed entries as Stock
   Reconciliations of 200 entries each. A quantity 0 row needs no valuation rate. A failing chunk is logged and does not stop the next
   chunk.
6. Final log line: `Seen <n>, not in ERPNext <n>, stock changed on <n>.`
   `status=failed` with `error_message` "Stock was not updated: ..." when any
   chunk failed, or "<n> stock row(s) not updated: no valuation rate in
   ERPNext" when rows were skipped, otherwise `success`.

### Stored Cloudstore quantities

Item Supplier Attribute rows on the variant, supplier = **Supplier**, connector
name `cloudstore`:

| Key | Value |
|---|---|
| `cloudstore_qty` | `qty` of the item, or the sum over `whs[]` when `qty` is missing |
| `cloudstore_stock` | JSON list `[{"wh_id": ..., "qty": ...}]` |
| `cloudstore_stock_at` | time of the last run in which `cloudstore_qty` or `cloudstore_stock` changed |

All three are written only when something changed. The item sync keeps these
three rows when it replaces the other Cloudstore attribute rows.

These rows hold Cloudstore's number. ERPNext's own stock can differ after sales.

## Event stock updates

`ITEMS_AVAILABILITY_UPDATED` events set stock for one warehouse only. See
[events.md](events.md).
