# Cloudstore API reference

Source: the Cloudstore Shops API spec (title "CloudStore Shops API"). Base URL
is configured in the settings and ends in `/shop/v1`. Every call sends
`Authorization: Bearer <token>`.

## Endpoints

"Connector call" is the method in `cloudstore/endpoints/` (reached as
`client.<resource>.<method>`). "Used by" names the feature that calls it; "no
feature" means the method exists but no job or button calls it.

| Method | Path | Connector call | Used by |
|---|---|---|---|
| GET | `/categories` | `categories.list` | no feature |
| GET | `/categories/roots` | `categories.roots` | category browse |
| GET | `/categories/tree` | `categories.tree` | category sync, Test Connection |
| GET | `/categories/{id}` | `categories.get` | no feature |
| GET | `/categories/{id}/children` | `categories.children` | category browse |
| GET | `/items` | `items.paginated` | item sync, stock sync |
| GET | `/items/findByCode` | `items.find_by_code` | `sync_skus`, `lookup_item` |
| GET | `/items/listByCode` | `items.list_by_code` | `find_items` |
| POST | `/items/listByParentSKUList` | `items.list_by_parent_skus` | `sync_parents`, `lookup_item` |
| GET | `/items/listBySearchTerm` | `items.search` | `search_items` |
| GET | `/items/{id}` | `items.get` | no feature |
| POST | `/v2/items/listParentsByFilter` | `items.list_parents_by_filter` | `sync_filtered` |
| GET | `/items/listByCategoryAndBrandAndSeason` | `items.list_by_category_brand_season` | no feature. Not in the spec; present in the vendor's Postman collection only. |
| POST | `/orders` | `orders.create` | order push |
| GET | `/orders/findByShopOrderId` | `orders.find_by_shop_order_id` | order push (fallback), status refresh |
| GET | `/orders/listByFilter` | `orders.list` | no feature |
| GET | `/orders/{id}` | `orders.get` | no feature |
| PUT | `/orders/{id}` | `orders.replace` | no feature |
| PATCH | `/orders/{id}` | `orders.patch` | no feature |
| DELETE | `/orders/{id}` | `orders.delete` | order cancel |
| GET | `/events` | `events.next_page` | events job |
| POST | `/events` | `events.create` | no feature. Sandbox only; production answers 403. |
| POST | `/inventory-catalog/start` | `inventory.start` | no feature |
| POST | `/inventory-catalog/{pageId}` | `inventory.upload_page` | no feature |
| POST | `/inventory-catalog/finished` | `inventory.finish` | no feature |
| GET | `/swagger.json` | `client.swagger()` | no feature |
| GET | `/ping` | none | not implemented. Answers 204. |

## Parameters

| Endpoint | Parameters |
|---|---|
| paged lists (`categories`, `roots`, `children`, `items`, `listByCode`, `listBySearchTerm`, `orders/listByFilter`, `listParentsByFilter`) | `_pageIndex` (from 0), `_pageSize`, `_sort` (`field[ASC]` or `field[DESC]`, comma separated). `/items` and `listBySearchTerm` allow at most 250 per page. |
| `/items` | `withQuantities`, `customerId` |
| `findByCode`, `listByCode` | `type` (`BARCODE`, `BARCODES`, `EAN`, `ITEM_ID`, `MNF_CODE`, `MPN`, `NS_INTERNAL_ID`, `SKU`, `SKU_PARENT`, `UPC`), `code`, `customerId`. `listByCode` also `_searchType` (`EXACT`, `PARTIAL_CASE_SENSITIVE`, `PARTIAL_CASE_INSENSITIVE`; the server default is `PARTIAL_CASE_INSENSITIVE`). |
| `listBySearchTerm` | `searchTerm`, `customerId` |
| `items/{id}`, `listByParentSKUList` | `customerId` |
| `orders/listByFilter` | `dateFrom`, `dateTo`, `statuses` (repeated), `searchTerm`, `buyerId`, `additionalInfoKey`, `additionalInfoValue` |
| `orders/findByShopOrderId` | `shopOrderId` |
| `listParentsByFilter` | `withQuantities`, `customerId`; body is required but may be `{}` |
| `/events` | none. Header `X-API-Feature` is declared without description and is not sent. |

`customerId`: when given, the reply adds `additional_info` with the customer's
own price (`customer_price`). The connector does not send it.

Sorting on `listParentsByFilter` is limited to `parent_sku` (aliases `_id`,
`sku_parent`) and `last_info_update`.

## Reply shapes

| Shape | Used by | Structure |
|---|---|---|
| list envelope | all paged lists | `{_metadata: {page_index, page_size, total_pages, total_items}, additional_info, content: [ ... ]}` |
| single envelope | `/{id}`, `findByCode`, orders create, replace, patch, `findByShopOrderId` | `{_metadata: {creation_dt, last_update_dt}, additional_info, content: {...}}` |
| tree | `/categories/tree` | plain array of `{id: {$oid}, level, name, children[]}` |
| parents | `listParentsByFilter` | `content: [{parent_sku, items: [Item]}]` |

Ids are objects `{"$oid": "..."}`. Dates are `{"$date": "..."}`.

### Item (`ShopItem`)

`item_id`, `sku`, `barcodes[{creation_dt, update_dt, code}]`, `stock_price`,
`sale_price`, `qty`, `cats[]`, `abs[{ab_id, qty, stock_price, shops[], lst_excl_shops[]}]`,
`whs[{wh_id, qty, shops_reservation[{r_id, created_dt, updated_dt, shop_ids[], qty}]}]`,
`locs{singles, lists}`, `imgs[{url, pos, placement[], excluded_shops[]}]`,
`composition[{material, perc, part}]`, `linked_items[{type, item_id, qty, shops_excluded[]}]`,
`props`, `lst_info_update_dt`, `pb`, `bc[{condition_id, price}]`,
`external_identifiers{externalKey, nsInternalId, shopInternalId}`, `search_tags[]`.

Which of these are stored is listed in [items.md](items.md).

### Category

`_id`, `created_dt`, `updated_dt`, `name {locs: {<language>: text}}`, `leaf`,
`parent_id`, `ext_ids`. The tree call returns `ApiCategory` instead:
`id`, `level`, `name` (plain text), `children[]`.

### Order

`_id`, `shop_id`, `shop_order_id`, `order_status`, `order_dt`,
`last_status_update_dt`, `creation_dt`, `update_dt`, `tot_qty`, `tot_amount`,
`price_adjustments[]`, `buyer_identifier`, `buyer_email`, `buyer_name`,
`billing_info`, `shipping_info`, `fulfillment_channel` (`CUSTOMER`,
`MARKETPLACE`), `items[]`, `documents`, `status_history[]` (`from`,
`status`, `module_id`, `created_dt`), `additional_info`, `packaging_info`.

Order create accepts `{order, _metadata: {processing_options: {partial_order,
warehouse_module: {selected_whs[]}}}}`. The connector sends only `order`.

### Event (`PersonalShopEvent`)

`_id`, `type`, `date`, `shop_id`, `items[{item_id, sku, qty, order_id,
stock_price, sale_price, item}]`, `shop_order_id`, `new_status`, `shipment`.

Types: `ITEMS_AVAILABILITY_AND_PRICE_UPDATED`, `ITEMS_AVAILABILITY_UPDATED`,
`ITEMS_CATALOG_UPDATED`, `ITEMS_PRICE_UPDATED`, `ITEMS_REMOVED`,
`ORDER_STATUS_UPDATED`, `SHIPMENT_UPSERTED`.

### Shipment

`_id`, `date`, `carrier`, `method`, `tracking_number`, `tracking_url`,
`return_tracking_number`, `exp_delivery_date`, `delivery_date`, `cost`,
`first_name`, `last_name`, `company_name`, `address`, `contacts`,
`orders[{order_id, order_type, items[{sku, qty}]}]`, `external_identifiers`,
`status_history[{status, date, note}]`, `additional_info`. Shipment statuses:
`SHIPPED`, `PARTIALLY_SHIPPED`, `ONGOING`, `DELIVERED`.

## Status codes

Every endpoint can answer 401 and 429 (rate limited) and 500. Order and event
calls document 400. Single reads document 404, some 403. The inventory calls
document 409.
