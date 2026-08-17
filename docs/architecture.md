# Architecture & Sync Engine

The plumbing shared across every domain: auth, the API client, how
duplicate/redundant writes are avoided, retries, logging, webhooks.

---

## Connector pattern

Standalone Frappe app (`alaiy_os_connector_cloudstore`) that registers into
Alaiy OS's Connector Registry (`OS Connector Registry`) on `after_migrate`
via `setup/install.py::sync_connector_registry()`, sourced from the single
metadata dict in `connector_meta.py`. Settings live in a Single DocType
(`Cloudstore Connector Settings`); every sync run is recorded as a
`Cloudstore Sync Log` document.

## Auth & client

`cloudstore/client.py::CloudstoreClient` is a thin wrapper around
`requests.Session`. On construction it reads `cs_api_url` and
`cs_bearer_token` from the settings Single doc, throws
`frappe.ValidationError` if either is missing, and sets
`Authorization: Bearer <token>` as a default session header. It exposes only
two methods:

- `get(path, params)` — single GET, `timeout=20`, raises `RuntimeError` on
  any non-2xx response (no retry). This is the entire error-handling
  behavior of the client: one attempt, no exponential backoff, no re-queue.
- `get_paginated(path, params, page_size)` — a generator that walks
  Cloudstore's `_pageIndex`/`_pageSize`/`_metadata.total_pages` pagination,
  with SKU-based loop detection (if a page returns only SKUs already seen,
  it's treated as a stuck loop and logged/stopped rather than looping
  forever).

**Confirmed: there is no retry logic anywhere in this connector.** A single
failed HTTP call — a timeout, a 5xx, a transient network blip — raises
immediately, is caught by the outer `try/except` in `sync_categories.run` /
`sync_items.run`, and marks the whole sync run `failed`. The next attempt
only happens on the next scheduled tick or a manual re-trigger; nothing
inside a single run retries a failed request. `api/test_connection.py`
similarly makes exactly one request with a 10s timeout and no retry.

## Change detection & identity

- **Categories**: matched by Cloudstore's own category oid stored in Item
  Group's `supplier_id` custom field — never by name, since category names
  repeat across unrelated branches of the tree.
- **Items**: matched by `sku` (variant) and `sku_parent__mnf_color_code`
  (template). Every item in every page is unconditionally re-upserted
  (fields overwritten) on every run — there is no "skip if unchanged"
  optimization or content hashing. `last_synced_at` is stamped on every
  variant every run, whether or not anything actually changed.
- **Stock**: a single Stock Reconciliation batches all resolved
  warehouse/qty entries from the whole run, submitted once at the end
  rather than per item.

## Sync log / error visibility

`Cloudstore Sync Log` (autoname `CS-SYNC-.YYYY.-.MM.-.DD.-.######`) records,
per run: `sync_type` (categories/items), `trigger` (scheduled/manual),
`status` (running/success/failed/skipped), `started_at`/`finished_at`,
`items_processed`/`created`/`updated`/`failed`, `pages_total`/`pages_done`
(items only), `error_message` (truncated to 1000 chars), and a free-text
`log_messages` field that accumulates per-item error lines during the run.
It's exposed in the Alaiy OS sidebar under "Cloudstore Logs"
(`alaiy_os_sidebar_log_items` hook) and via the whitelisted
`api.sync.get_sync_status(sync_type)`, which returns the last 3 logs.
Per-item failures inside a run (e.g. one bad SKU) are caught, counted in
`items_failed`, logged via `frappe.log_error`, and do not abort the rest of
the run — only a failure outside that inner loop (e.g. the initial
`/categories/tree` or `/items` request itself) fails the whole run.
