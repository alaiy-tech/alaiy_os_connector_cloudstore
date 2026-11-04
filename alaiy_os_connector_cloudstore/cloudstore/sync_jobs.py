# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, add_to_date

from alaiy_os_connector_cloudstore.cloudstore.run_guard import active_run

# After a failed run, wait at least this long (or the interval, if longer) before trying again.
FAILURE_BACKOFF_MINUTES = 5


_INTERVAL_MINUTES = {
    "1 min": 1,
    "5 min": 5,
    "10 min": 10,
    "30 min": 30,
    "1 hour": 60,
    "6 hours": 360,
    "1 day": 1440,
}


def check_and_enqueue():
    """
    Called every minute by the Frappe scheduler (hooks.py cron).

    Reads the configured sync intervals from Cloudstore Connector Settings and,
    for each sync type, decides whether to enqueue a background job based on:

    - Whether the interval is "Disabled" (skip).
    - Whether a job is genuinely still running (the run guard's 120-minute rule).
    - Whether the last attempt is still inside its wait: the interval after a
      success, and at least FAILURE_BACKOFF_MINUTES after a failure.
    """
    if not frappe.db.exists("DocType", "Cloudstore Sync Log"):
        return

    settings = frappe.get_single("Cloudstore Connector Settings")

    if not settings.is_enabled:
        return

    _maybe_enqueue(
        interval_setting=settings.cs_category_sync_interval,
        sync_type="categories",
        enqueue_fn="alaiy_os_connector_cloudstore.cloudstore.sync_categories.run",
    )
    _maybe_enqueue(
        interval_setting=settings.cs_items_sync_interval,
        sync_type="items",
        enqueue_fn="alaiy_os_connector_cloudstore.cloudstore.sync_items.run",
    )
    _maybe_enqueue(
        interval_setting=settings.cs_stock_sync_interval,
        sync_type="stock",
        enqueue_fn="alaiy_os_connector_cloudstore.cloudstore.sync_stock.run",
    )
    _maybe_enqueue(
        interval_setting=settings.cs_orders_sync_interval,
        sync_type="orders",
        enqueue_fn="alaiy_os_connector_cloudstore.cloudstore.sync_orders.run",
    )
    _maybe_enqueue(
        interval_setting=settings.cs_events_sync_interval,
        sync_type="events",
        enqueue_fn="alaiy_os_connector_cloudstore.cloudstore.sync_events.run",
    )


def _maybe_enqueue(interval_setting: str, sync_type: str, enqueue_fn: str):
    """
    Enqueue a sync job for sync_type if it is due.

    Args:
        interval_setting: Value from the Select field, e.g. "Disabled", "5 min".
        sync_type:        "categories", "items", "stock", "orders" or "events".
        enqueue_fn:       Dotted path to the Frappe-enqueue-able function.
    """
    if interval_setting in (None, "", "Disabled"):
        return
    interval_minutes = _INTERVAL_MINUTES.get(interval_setting)
    if not interval_minutes and str(interval_setting).strip().isdigit():
        # A bare number (e.g. written through the API) means minutes.
        interval_minutes = int(interval_setting)
    if not interval_minutes:
        # Logger, not Error Log: this runs every minute and would flood it.
        frappe.logger("cloudstore").warning(f"{sync_type}: interval '{interval_setting}' not recognised, sync skipped")
        return

    now = now_datetime()

    # ------------------------------------------------------------------
    # Guard: a run is genuinely still in flight (also clears orphaned logs)
    # ------------------------------------------------------------------
    if active_run(sync_type):
        return

    # ------------------------------------------------------------------
    # Guard: the last attempt is still inside its wait
    # ------------------------------------------------------------------
    last_attempt = frappe.db.get_value(
        "Cloudstore Sync Log",
        {"sync_type": sync_type, "status": ["in", ["success", "failed"]]},
        ["status", "started_at"],
        order_by="started_at desc",
        as_dict=True,
    )
    if last_attempt and last_attempt.started_at:
        wait = interval_minutes if last_attempt.status == "success" else max(interval_minutes, FAILURE_BACKOFF_MINUTES)
        if now < add_to_date(last_attempt.started_at, minutes=wait):
            return

    # Due — enqueue on the long queue
    frappe.enqueue(enqueue_fn, queue="long", trigger="scheduled")
