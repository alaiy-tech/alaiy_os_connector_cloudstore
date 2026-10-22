# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""
Cloudstore events: GET /events returns the "next events page". There are no
paging parameters, so a page that was read is treated as consumed: every
event is written to the Sync Log, whether or not it could be applied.

Event types and what happens:
  ORDER_STATUS_UPDATED   new status on the Sales Order
  SHIPMENT_UPSERTED      carrier, tracking and shipment status on the Sales Order
  ITEMS_*                stock, price, catalogue and removal, see item_events

POST /events exists only in the Cloudstore sandbox (403 in production), so
nothing is ever pushed from here.
"""

import json

import frappe
from frappe.utils import now_datetime

from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient
from alaiy_os_connector_cloudstore.cloudstore.item_events import ITEM_EVENTS, apply_item_event
from alaiy_os_connector_cloudstore.cloudstore.sync_orders import apply_order_event

_MAX_PAGES = 20


def run(trigger: str = "scheduled") -> str:
    """Background job: read pending events, apply them, one Sync Log row."""
    log = frappe.new_doc("Cloudstore Sync Log")
    log.sync_type = "events"
    log.trigger = trigger
    log.status = "running"
    log.started_at = now_datetime()
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        settings = frappe.get_single("Cloudstore Connector Settings")
        events = read_events(CloudstoreClient())
        lines, failed = [], 0
        for event in events:
            try:
                lines.append(f"{event.get('type')}: {apply_event(event, settings)}")
            except Exception as exc:
                failed += 1
                lines.append(f"ERROR {event.get('type')}: {exc}")
                frappe.log_error(title="Cloudstore event failed", message=frappe.get_traceback())
        log.items_processed = len(events)
        log.items_failed = failed
        log.items_updated = len(events) - failed
        # Raw events last: they are the only copy of what the API handed over.
        log.log_messages = "\n".join(
            lines + ["EVENT " + json.dumps(e, ensure_ascii=False, default=str) for e in events]
        )
        log.status = "failed" if failed else "success"
        if failed:
            log.error_message = f"{failed} event(s) could not be applied, see log."
    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)[:1000]
        frappe.log_error(title="Cloudstore events sync failed", message=frappe.get_traceback())
    finally:
        log.finished_at = now_datetime()
        log.save(ignore_permissions=True)
        frappe.db.commit()
    return log.name


def read_events(client) -> list:
    """Read event pages until an empty one, at most _MAX_PAGES."""
    events, previous_first = [], None
    for _ in range(_MAX_PAGES):
        rows = (client.events.next_page() or {}).get("content") or []
        if not rows:
            break
        first = (rows[0].get("_id") or {}).get("$oid")
        if first and first == previous_first:
            break  # the server is not moving forward: stop instead of looping
        previous_first = first
        events += rows
    return events


def apply_event(event: dict, settings) -> str:
    event_type = event.get("type")
    if event_type in ("ORDER_STATUS_UPDATED", "SHIPMENT_UPSERTED"):
        hit = apply_order_event(event.get("shop_order_id"), event.get("new_status"), event.get("shipment"))
        return "applied to Sales Order" if hit else "no matching Sales Order"
    if event_type in ITEM_EVENTS:
        return apply_item_event(event, settings)
    return "type not handled"
