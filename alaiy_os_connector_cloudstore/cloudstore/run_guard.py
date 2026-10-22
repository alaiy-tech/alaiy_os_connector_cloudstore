# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""One run at a time per sync type, for every Cloudstore job."""

import frappe
from frappe.utils import add_to_date, now_datetime

# A "running" log older than this is treated as orphaned (worker killed mid-run).
STALE_RUNNING_MINUTES = 120


def active_run(sync_type: str) -> bool:
    """
    True if a run of this sync type is genuinely still in flight. A "running"
    log older than STALE_RUNNING_MINUTES is marked failed so it stops blocking
    future runs.
    """
    cutoff = add_to_date(now_datetime(), minutes=-STALE_RUNNING_MINUTES)
    running = frappe.get_all(
        "Cloudstore Sync Log",
        filters={"sync_type": sync_type, "status": "running"},
        fields=["name", "started_at"],
    )
    active = False
    for row in running:
        if row.started_at and row.started_at < cutoff:
            frappe.db.set_value("Cloudstore Sync Log", row.name, {
                "status": "failed",
                "finished_at": now_datetime(),
                "error_message": "Marked failed: orphaned running log (worker likely restarted mid-run).",
            })
        else:
            active = True
    if running:
        frappe.db.commit()
    return active


def skip_if_active(sync_type: str, trigger: str):
    """
    Call first in a job's run(). When another run of the same type is active,
    writes a log with status "skipped" and returns its name, and the job must
    return it. Returns None when the job may proceed.
    """
    if not active_run(sync_type):
        return None
    log = frappe.new_doc("Cloudstore Sync Log")
    log.sync_type = sync_type
    log.trigger = trigger
    log.status = "skipped"
    log.started_at = now_datetime()
    log.finished_at = now_datetime()
    log.error_message = f"Skipped: another {sync_type} sync is already running."
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log.name
