# Setup & Configuration

Cloudstore is a standalone Frappe app that plugs into Alaiy OS's Connector
Registry. It ships disabled (`is_enabled = 0`). Turning it on for the first
time provisions custom fields on Item/Item Group, the Size/Color Item
Attributes, a placeholder Supplier, and two Price Lists — it does not
register any webhook (Cloudstore has none configured here; sync is entirely
poll/schedule-driven).

---

## 1. Prerequisites
- Frappe bench with `alaiy_os` and `erpnext` installed (`required_apps` in `hooks.py`)
- A Cloudstore API base URL and a Bearer Token for your shop, issued by
  Cloudstore directly — this connector has no OAuth/token-minting flow, it
  only stores and replays a token you paste in.

## 2. Cloudstore credentials

| Cloudstore-side value | Settings field | Notes |
|---|---|---|
| API base URL | `cs_api_url` (Data) | Stored as plain text; trailing `/` stripped by the client |
| Bearer token | `cs_bearer_token` (Password) | Pasted directly, not minted by the connector; sent as `Authorization: Bearer <token>` on every request |

There is no OAuth or client-credentials exchange anywhere in this code —
the token is whatever value you paste into the field.

## 3. Cloudstore Connector Settings — every field

DocType: `Cloudstore Connector Settings` (Single).

**API Connection**
| Field | Type | Purpose |
|---|---|---|
| `cs_api_url` | Data, required | Cloudstore API base URL |
| `cs_bearer_token` | Password, required | Bearer token sent on every API call |

**Sync Defaults**
| Field | Type | Purpose |
|---|---|---|
| `cs_supplier` | Link → Supplier, required | Supplier every synced Item/template is linked to |
| `cs_sync_warehouse` | Link → Warehouse, required | Default warehouse for any Cloudstore `whs[].wh_id` not yet in the mapping table |
| `cs_warehouse_mapping` | Table (Cloudstore Warehouse Mapping) | Maps each Cloudstore warehouse ID to an ERPNext Warehouse; unmapped IDs are auto-added here pointed at the default, so you can re-point them later |
| `cs_buying_price_list` | Link → Price List, required | Price list written with `stock_price` (buy cost) from Cloudstore |
| `cs_price_list` | Link → Price List, required | Price list written with `sale_price` from Cloudstore |

**Sync Schedule**
| Field | Type | Purpose |
|---|---|---|
| `cs_page_size` | Int, required, default 250 | Items per page for `/items` (Cloudstore's own cap is 250) |
| `cs_category_sync_interval` | Select, required, default `Disabled` | `Disabled` / `1 min` / `5 min` / `10 min` / `30 min` — how often the category tree auto-syncs |
| `cs_items_sync_interval` | Select, required, default `Disabled` | Same options — how often items auto-sync |

Child table `Cloudstore Warehouse Mapping`: `cs_wh_id` (Data, unique,
required) → `warehouse` (Link → Warehouse, required).

## 4. First enable

The moment `is_enabled` flips `0 → 1` (caught in
`CloudstoreConnectorSettings.validate()`), the connector runs, in order:

1. `setup_custom_fields()` — adds `supplier_id` + `supplier_cat_level` to
   Item Group, and `supplier_id`, `sku_parent`, `mnf_color_code`,
   `last_synced_at`, `manufacturer_color`, `hs_code` to Item.
2. `setup_item_attributes()` — creates the `Size` and `Color` Item
   Attributes if they don't already exist (needed before any variant can be
   saved).
3. `create_default_supplier()` — creates Supplier "Cloudstore (The Corner)"
   under Supplier Group "International Brands" if absent (this is a
   placeholder; the actual Supplier used by syncs is whatever `cs_supplier`
   points to).
4. `create_default_price_lists()` — creates "Cloudstore - Buying" and
   "Cloudstore - Selling" Price Lists (INR) if absent.

It also flips `OS Connector Registry.is_enabled` for `cloudstore` to match,
every time the setting is saved (not just on first enable). Disabling the
connector (`1 → 0`) does not run any teardown — no custom fields, price
lists, or the placeholder Supplier are removed, and no webhook needs
unregistering because none was ever registered.

Separately, on every `bench migrate`, `sync_connector_registry()` (via
`after_migrate`) upserts this connector's row in the OS Connector Registry
and re-runs Alaiy OS's sidebar provisioning — this is registry bookkeeping,
not credential or field setup.
