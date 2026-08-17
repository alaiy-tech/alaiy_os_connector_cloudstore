# Cloudstore Connector — what it actually does

Cloudstore is a third-party supplier catalogue/inventory platform ("The
Corner"). Alaiy OS is the ERPNext-based ops system. This connector pulls
Cloudstore's category tree and item catalogue (with stock quantities) into
Alaiy OS as Item Groups, Items, Item Prices and Stock Reconciliations. It is
a **one-way, inbound-only, read-only-against-Cloudstore** connector — nothing
in this codebase writes anything back to Cloudstore.

---

## The short version

| | Direction | Automatic? |
|---|---|---|
| Category tree | Cloudstore → Alaiy OS (Item Groups) | yes, on the configured interval (or "Disabled"), plus a manual "Sync Category Tree" button |
| Items, variants, prices, stock | Cloudstore → Alaiy OS (Items, Item Prices, Stock Reconciliation) | yes, on the configured interval (or "Disabled"), plus a manual "Sync Items" button |
| Orders / shipping | Not built | — the registry description calls Cloudstore "supplier catalogue, orders & shipping", but no order or shipping code exists anywhere in this repo |

**Nothing syncs at all until the connector is enabled** (`is_enabled` on
Cloudstore Connector Settings), and even once enabled, category/item syncs
only run automatically if their own interval field is set to something other
than "Disabled" — the default for both is "Disabled". Nothing ever writes to
Cloudstore; this connector only reads from it.

---

## Coming IN from Cloudstore

### Category tree → Item Groups
Every minute, a scheduler tick (`sync_jobs.check_and_enqueue`) checks whether
a categories sync is due (interval elapsed, no run already in flight) and, if
so, enqueues `sync_categories.run` on the `long` queue. It fetches
`/categories/tree` once and recursively upserts each node as an ERPNext Item
Group, matched by Cloudstore's own category ID (never by name — category
names repeat across unrelated branches of the tree).

### Items, variants, prices, stock → Items / Item Prices / Stock Reconciliation
On its own interval, `sync_items.run` pages through `/items` (with
quantities), and for each item:
- upserts a **template** Item (`has_variants=1`, keyed by `sku_parent__mnf_color_code`)
- upserts a **variant** Item (keyed by the Cloudstore `sku`, `Size` as the
  only variant attribute)
- upserts Item Prices in the configured buying and selling price lists
- links the configured Supplier to both template and variant
- writes supplier-specific attributes (season, collection, HS code, etc.)
- builds a Website Slideshow from any extra images
- collects per-warehouse stock quantities across all pages, then submits
  **one** Stock Reconciliation per run for everything synced

Only one items sync can be "running" at a time — a second sync request
while one is active is logged as `skipped`, not run. A "running" log older
than 2 hours is treated as orphaned (worker likely died) and force-marked
`failed` so it stops permanently blocking future runs.

## Going OUT to Cloudstore

Nothing. There is no outbound flow in this connector — no order push, no
stock push, no product push. `client.py` only exposes `get()` /
`get_paginated()`; there is no `post()`/`put()`/`patch()` method at all.
