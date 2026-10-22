# Orders

Code: `cloudstore/sync_orders.py`, `cloudstore/order_payload.py`. Hooks in
`hooks.py`: Sales Order `on_submit` and `on_cancel`.

The submit and cancel hooks run only when **Enable Cloudstore** and **Send Sales
Orders to Cloudstore** (`cs_push_orders`) are both set. The status refresh job
runs on its own interval and needs **Enable Cloudstore**.

## Fields on the Sales Order

All read only, editable after submit. Written with `frappe.db.set_value`
(`update_modified=False`), so no document hooks fire.

| Field | Content |
|---|---|
| `cs_order_id` | Cloudstore order id (`_id.$oid` from the reply). Set means "already sent". |
| `cs_order_status` | Last known Cloudstore status string |
| `cs_push_error` | Last failure text, up to 500 characters; cleared on success |
| `cs_carrier`, `cs_tracking_number`, `cs_tracking_url` | From the last shipment event |
| `cs_shipment_status` | Last entry of the shipment's `status_history` |

## Push

### Trigger

`on_sales_order_submit` returns unless the connector is enabled and `cs_push_orders` is on. Otherwise it
enqueues `push_order(sales_order)` on the `short` queue with
`enqueue_after_commit=True`. The submit itself does not wait for Cloudstore.

Manual: `api.sync.push_sales_order(sales_order)` (System Manager or Sales
Manager) runs `push_order` in the request, for a retry.

### `push_order(sales_order)`

| Condition | Result |
|---|---|
| `cs_order_id` already set | returns `{skipped: "already pushed"}`, nothing sent |
| no line of the Sales Order belongs to a Cloudstore item | returns `{skipped: "no Cloudstore items"}` |
| otherwise | `POST /orders`, then stores the result |

A line belongs to a Cloudstore item when its Item has `supplier_id` set.
Other lines are not sent.

After `POST /orders` the order id is read from `content._id.$oid` of the reply.
If it is missing, `GET /orders/findByShopOrderId` with the Sales Order name is
called and the id read from there. If still missing, the push fails with
"Order created but no id in Cloudstore reply".

On success: `cs_order_id`, `cs_order_status` (from `content.order_status`) are
set and `cs_push_error` is cleared. On any exception: `cs_push_error` is set,
an Error Log entry is written, and `{error: ...}` is returned.

### Retry of failed pushes

`retry_failed_pushes` runs at the start of every orders job (the job with
**Order Status Refresh Interval**, so that interval must be set). It needs the
connector enabled and **Send Sales Orders to Cloudstore** on.

It selects submitted Sales Orders dated within the last 2 days with
`cs_order_id` empty and `cs_push_error` set, and calls `push_order` again for
those whose error text contains one of: `Cloudstore API error 429`,
`Cloudstore API error 5`, `Connection`, `Timeout`, `timed out`. Other errors,
such as a rejection with HTTP 400 for an unknown SKU, are left in
`cs_push_error`: they would fail the same way. After fixing the cause, call
`api.sync.push_sales_order`.

The log line `Push retries: <n> tried, <n> sent.` is written when at least one
retry ran. A failed cancel (`cs_order_id` set) is not retried.

### Request body: `order_payload.build_order_payload`

```
{"order": {
  "shop_order_id": <Sales Order name>,
  "order_status": <cs_order_push_status>,
  "order_dt": {"$date": <creation as YYYY-MM-DDTHH:MM:SS.000Z>},
  "buyer_email": <contact_email>,
  "buyer_name": <customer_name>,
  "items": [ per Cloudstore line:
    {"item_id": {"$oid": <Item.supplier_id>},
     "sku": <item_code>,
     "qty": <int(qty)>,
     "price": <net_rate, else rate>,
     "unit_price_tax_excl": {"amount": <net_rate or rate>, "currency": <currency>},
     "unit_price_tax_incl": {"amount": round(excl * grand_total / net_total, 2), "currency": <currency>}} ],
  "additional_info": {},
  "shipping_info": {"address": <shipping_address_name, else customer_address>},
  "billing_info":  {"address": <customer_address>}
}}
```

Address object, from the linked Address: `street` (`address_line1` and
`address_line2` joined by `, `), `city`, `state`, `zip` (`pincode`), `contact1`
(`phone`). No linked address gives `{}`.

`tot_qty`, `tot_amount`, `_id`, `shop_id` and the date fields set by Cloudstore
are not sent; Cloudstore ignores or recalculates them.

### Cloudstore rules for create (from the API spec)

- Required: `shop_order_id`, `order_status`, `order_dt`.
- Allowed statuses on create: `PENDING`, `CONFIRMED`. `items` is required only
  for `CONFIRMED`; each item needs `sku`, `qty`, `price`.
- Money fields need an ISO currency; one currency per order.
- An order with unknown items is rejected with HTTP 400 and a message of the
  form `Order not accepted. Invalid item(s) are the following: [SKU1, SKU2]
  [ERROR_CODE]`. That text ends up in `cs_push_error`.

## Cancel

`on_sales_order_cancel` returns unless the connector is enabled and `cs_push_orders` is on, or when the Sales Order
has no `cs_order_id`. Otherwise it enqueues `cancel_order` on `short`.

`cancel_order` calls `DELETE /orders/{cs_order_id}`. Cloudstore keeps the order,
marks it `CANCELED` and releases the allocated quantity. On success
`cs_order_status` = `CANCELED`. On failure `cs_push_error` = `Cancel failed: ...`
and an Error Log entry is written.

Amending a Sales Order in ERPNext cancels the old one (delete on Cloudstore)
and submits a new one under a new name (new order on Cloudstore).

## Status refresh

Scheduler job `sync_orders.run` (interval `cs_orders_sync_interval`), or
`api.sync.trigger_orders_sync` (System Manager or Sales Manager).

For every Sales Order with `cs_order_id` set and `transaction_date` within the
last 30 days: `GET /orders/findByShopOrderId` with the Sales Order name, and
`cs_order_status` is updated when `content.order_status` differs. Log counts:
`items_processed` = orders checked, `items_updated` = status changed,
`items_failed` = orders whose call failed. Per-order failures do not fail the
run; the status is `success` unless an exception ends the whole job.

## Cloudstore order statuses

`PENDING`, `CONFIRMED`, `CANCELED`, `REFURBISHED`, `SHIPPED`,
`PARTIALLY_SHIPPED`, `OTHER`. Allowed changes through the API: `PENDING` to
`CONFIRMED`, `PENDING` to `CANCELED`, `CONFIRMED` to `CANCELED`. The connector
stores the status string as received and does not interpret it.

## Events that update orders

`ORDER_STATUS_UPDATED` and `SHIPMENT_UPSERTED` events change the Sales Order
fields above. See [events.md](events.md).
