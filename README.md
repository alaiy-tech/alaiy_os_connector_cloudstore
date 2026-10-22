# Alaiy OS Connector: Cloudstore

Connects a Cloudstore supplier account to [Alaiy OS](https://alaiy.com).
Cloudstore is read into ERPNext: category tree, item catalogue, prices and
stock. Sales Orders can be sent to Cloudstore, and Cloudstore events (order
status, shipments, stock, prices) are read back.

## Features

- **Category sync**: Cloudstore categories to Item Groups.
- **Item sync**: items as template and variant Items with prices, supplier
  link, barcodes, images and every other field Cloudstore returns.
- **Stock sync**: stock-only update that keeps Cloudstore quantities on the
  Item and changes ERPNext stock only where it differs.
- **Order push**: submitted Sales Orders (Cloudstore items only) are sent to
  Cloudstore, cancelled there on cancel, and their status is refreshed.
- **Events**: order status, shipment, price, stock, catalogue and removal
  events are applied.
- **On-demand tools**: search, lookup, single-item and filtered sync,
  category browse.
- **Sync log**: every run is recorded in Cloudstore Sync Log.

Every scheduled job is disabled until its interval is set. Order push is off
until **Send Sales Orders to Cloudstore** is set.

## Setup

1. Open **Cloudstore Connector Settings**. Enter the API URL (ending in
   `/shop/v1`) and the Bearer Token.
2. Choose the Supplier, Default Sync Warehouse, Buying Price List and Selling
   Price List.
3. Click **Test Connection**.
4. Enable the connector and save.
5. Run **Sync Category Tree**, then **Sync Items**.

## Documentation

Technical docs are in [docs/](docs/index.md).

## License

AGPL-3.0
