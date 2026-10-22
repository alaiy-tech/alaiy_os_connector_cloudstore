# Architecture

## Package layout

Root: `alaiy_os_connector_cloudstore/alaiy_os_connector_cloudstore/`

| Path | Role |
|---|---|
| `hooks.py` | Registers install and migrate hooks, the Sales Order submit and cancel hooks, the sidebar log item, and the once-a-minute scheduler entry |
| `connector_meta.py` | Registry metadata: connector id `cloudstore`, type `supplier`, test method, sync methods for categories and items |
| `setup/install.py` | First-enable provisioning, migrate-time registry upsert, custom fields |
| `api/sync.py` | Whitelisted triggers: categories, items, stock, orders, events, status, raw lookup |
| `api/lookup.py` | Whitelisted search, lookup, single-item sync, filtered sync, category browse |
| `api/test_connection.py` | Connection test |
| `cloudstore/client.py` | HTTP transport and pagination |
| `cloudstore/endpoints/` | One class per Cloudstore resource: `categories.py`, `items.py`, `orders.py`, `events.py`, `inventory.py` |
| `cloudstore/sync_jobs.py` | Scheduler: decides every minute which job is due |
| `cloudstore/run_guard.py` | One run at a time per sync type, used by every job |
| `cloudstore/sync_categories.py` | Category tree to Item Groups |
| `cloudstore/sync_items.py` | Item sync, per-item upsert, price, supplier, warehouse and reconciliation helpers, `upsert_batch` |
| `cloudstore/item_attributes.py` | Builds the key/value list stored in Item Supplier Attribute |
| `cloudstore/sync_stock.py` | Stock-only sync |
| `cloudstore/order_payload.py` | Builds the Cloudstore order body from a Sales Order |
| `cloudstore/sync_orders.py` | Order push, cancel, status refresh, applying order events |
| `cloudstore/sync_events.py` | Reads event pages, dispatches by type |
| `cloudstore/item_events.py` | Applies item events (price, stock, catalogue, removal) |
| `cloudstore/sync_item_lookup.py` | Search, lookup, sync of chosen SKUs or parent SKUs |
| `cloudstore/sync_filtered.py` | Sync by brand, category or warehouse filter |
| `cloudstore/category_browse.py` | Read category roots and children |
| `doctype/cloudstore_connector_settings` | Settings Single and its buttons (`.js`) |
| `doctype/cloudstore_sync_log` | Run log DocType |
| `doctype/cloudstore_warehouse_mapping` | Child table of the settings |

## Client: `cloudstore/client.py`

`CloudstoreClient()` reads **Cloudstore Connector Settings** on creation.

| Step | Behaviour |
|---|---|
| API URL | Whitespace and a trailing `/` removed. Empty raises `frappe.ValidationError`. |
| Bearer token | Read with `get_password`. Missing raises `frappe.ValidationError`. |
| Page size | `int(cs_page_size or 250)` |
| Session | One `requests.Session` with header `Authorization: Bearer <token>` |
| Resources | `client.categories`, `.items`, `.orders`, `.events`, `.inventory` |

`request(method, path, params, json, files)`:

- URL is `api_url + path`, or `path` itself when it starts with `http`.
- Fixed timeout 20 seconds for every call, including uploads.
- Status outside 2xx raises `RuntimeError("Cloudstore API error <status> for <url>: <first 300 chars of body>")`.
- Returns the parsed JSON, or `{}` when the body is empty.
- No retry, no backoff, no handling of HTTP 429.

Wrappers: `get`, `post`, `put`, `patch`, `delete`, `swagger()` (`GET /swagger.json`).

`get_paginated(path, params, page_size)` is a generator yielding
`(new_items, metadata)` per page:

- Query: `_pageIndex` starting at 0, `_pageSize`.
- Items already seen by `sku` on an earlier page are dropped from `new_items`.
- If a page has items but none are new, it logs an Error Log entry
  "pagination loop detected" and stops.
- It stops after the page where `page_index + 1 >= _metadata.total_pages`.
- An empty page yields `([], metadata)` and continues.

Resource methods and their HTTP calls are listed in
[api-reference.md](api-reference.md).

## Scheduler: `cloudstore/sync_jobs.py`

`hooks.scheduler_events` runs `check_and_enqueue` every minute (`* * * * *`).

1. Returns at once if the Cloudstore Sync Log DocType does not exist or
   `is_enabled` is off.
2. Calls `_maybe_enqueue` for five job types:

| Setting | `sync_type` | Function enqueued |
|---|---|---|
| `cs_category_sync_interval` | `categories` | `sync_categories.run` |
| `cs_items_sync_interval` | `items` | `sync_items.run` |
| `cs_stock_sync_interval` | `stock` | `sync_stock.run` |
| `cs_orders_sync_interval` | `orders` | `sync_orders.run` |
| `cs_events_sync_interval` | `events` | `sync_events.run` |

`_maybe_enqueue(interval_setting, sync_type, enqueue_fn)`:

- Interval `Disabled` or unknown: nothing.
- A log of this type with status `running` and `started_at` less than 30
  minutes ago: nothing.
- The latest `success` log of this type with `started_at + interval` still in
  the future: nothing.
- Otherwise `frappe.enqueue(enqueue_fn, queue="long", trigger="scheduled")`.

Only successful runs delay the next one. After a failed run the job is due
again on the next minute tick.

## Sync log: Cloudstore Sync Log

| Field | Type | Meaning |
|---|---|---|
| `sync_type` | Select | `categories`, `items`, `stock`, `orders`, `events` |
| `trigger` | Select | `scheduled` or `manual` |
| `status` | Select | `running`, `success`, `failed`, `skipped` |
| `started_at`, `finished_at` | Datetime | Run window |
| `items_processed`, `items_created`, `items_updated`, `items_failed` | Int | Counts. Meaning per job is in each feature page. |
| `pages_total`, `pages_done` | Int | Pagination progress (items, stock) |
| `error_message` | Small Text | Reason a run failed |
| `log_messages` | Long Text | One line per warning or error, and raw events for the events job |

Every job writes its log with `running` first, then updates and finishes it in
a `finally` block, so `finished_at` is always set.

Unexpected exceptions are also written to Frappe's Error Log with a title that
names the job and, for per-item errors, the SKU.

## Run guard: `cloudstore/run_guard.py`

Every job (`categories`, `items`, `stock`, `orders`, `events`) calls
`skip_if_active(sync_type, trigger)` first.

- A `running` log of the same type younger than 120 minutes means another run is
  active. The call writes a log with `status=skipped` and the message "Skipped:
  another <type> sync is already running.", and the job returns that log name.
- A `running` log older than 120 minutes is marked `failed` ("orphaned running
  log") and does not block. This covers a worker killed mid-run.
- The scheduler's own check (running for under 30 minutes) only avoids queueing;
  the guard inside the job is what prevents two runs from overlapping when a job
  was queued twice.

## Queues

`sync_items.run_in_background` and the stock, orders and events triggers enqueue
on `long`. The Sales Order push and cancel use `short`, after commit.
