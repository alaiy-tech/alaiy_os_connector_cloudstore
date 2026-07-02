# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, add_to_date


_INTERVAL_MINUTES = {
    "1 min": 1,
    "5 min": 5,
    "10 min": 10,
    "30 min": 30,
}


def check_and_enqueue():
    """
    Called every minute by the Frappe scheduler (hooks.py cron).

    Reads the configured sync intervals from Cloudstore Connector Settings and,
    for each sync type, decides whether to enqueue a background job based on:

    - Whether the interval is "Disabled" (skip).
    - Whether a job is already running (started within the last 30 minutes).
    - Whether the last successful run is still within the configured interval.
    """
    if not frappe.db.exists("DocType", "Cloudstore Sync Log"):
        return

    settings = frappe.get_single("Cloudstore Connector Settings")

    if not settings.is_enabled:
        return

    _maybe_enqueue(
        interval_setting=settings.cs_category_sync_interval,
        sync_type="categories",
        enqueue_fn="alaiy_os_cloudstore_connector.cloudstore.sync_categories.run",
    )
    _maybe_enqueue(
        interval_setting=settings.cs_items_sync_interval,
        sync_type="items",
        enqueue_fn="alaiy_os_cloudstore_connector.cloudstore.sync_items.run",
    )


def _maybe_enqueue(interval_setting: str, sync_type: str, enqueue_fn: str):
    """
    Enqueue a sync job for sync_type if it is due.

    Args:
        interval_setting: Value from the Select field, e.g. "Disabled", "5 min".
        sync_type:        "categories" or "items".
        enqueue_fn:       Dotted path to the Frappe-enqueue-able function.
    """
    # "Disabled" or any unrecognised value — do nothing
    interval_minutes = _INTERVAL_MINUTES.get(interval_setting)
    if not interval_minutes:
        return

    now = now_datetime()

    # ------------------------------------------------------------------
    # Guard: a running job started within the last 30 minutes
    # ------------------------------------------------------------------
    running_started_at = frappe.db.get_value(
        "Cloudstore Sync Log",
        {"sync_type": sync_type, "status": "running"},
        "started_at",
        order_by="started_at desc",
    )
    if running_started_at:
        elapsed_seconds = (now - running_started_at).total_seconds()
        if elapsed_seconds < 1800:
            return

    # ------------------------------------------------------------------
    # Guard: last successful run is still within the configured interval
    # ------------------------------------------------------------------
    last_success_started_at = frappe.db.get_value(
        "Cloudstore Sync Log",
        {"sync_type": sync_type, "status": "success"},
        "started_at",
        order_by="started_at desc",
    )
    if last_success_started_at:
        due_at = add_to_date(last_success_started_at, minutes=interval_minutes)
        if now < due_at:
            return

    # Due — enqueue on the long queue
    frappe.enqueue(enqueue_fn, queue="long", trigger="scheduled")
