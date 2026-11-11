# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""One run at a time per sync type, for every Cloudstore job."""

import shutil

import frappe
from frappe.utils import add_to_date, now_datetime

# A "running" log older than this is treated as orphaned (worker killed mid-run).
STALE_RUNNING_MINUTES = 120

# The heavy writers (items, categories) skip a run when free disk is below this. A full disk
# stops the database and the job queue, which takes every site on the server down with it, so
# a sync that would write more is the wrong thing to run. Set `cloudstore_min_free_gb` in the
# site config to change it; 0 turns the guard off.
DEFAULT_MIN_FREE_GB = 1.0


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


def low_disk():
    """A message when free disk is under the floor, else None.

    Checks the site folder and the database's data folder (the same disk on most servers). A
    check that cannot run never blocks a sync: it fails open."""
    try:
        floor = float(frappe.conf.get("cloudstore_min_free_gb", DEFAULT_MIN_FREE_GB))
    except (TypeError, ValueError):
        floor = DEFAULT_MIN_FREE_GB
    if floor <= 0:
        return None
    paths = []
    try:
        paths.append(frappe.get_site_path())
    except Exception:
        pass
    try:
        paths.append(frappe.db.sql("select @@datadir")[0][0])
    except Exception:
        pass
    for path in paths:
        try:
            free_gb = shutil.disk_usage(path).free / 1024**3
        except (OSError, TypeError):
            continue
        if free_gb < floor:
            return (f"Skipped: only {free_gb:.1f} GB of disk is free (minimum {floor:g} GB). "
                    "Free some space; this sync resumes by itself.")
    return None


def _skipped_log(sync_type: str, trigger: str, message: str):
    log = frappe.new_doc("Cloudstore Sync Log")
    log.sync_type = sync_type
    log.trigger = trigger
    log.status = "skipped"
    log.started_at = now_datetime()
    log.finished_at = now_datetime()
    log.error_message = message
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log.name


def skip_if_active(sync_type: str, trigger: str, check_disk: bool = False):
    """
    Call first in a job's run(). When another run of the same type is active,
    writes a log with status "skipped" and returns its name, and the job must
    return it. Returns None when the job may proceed.
    """
    if check_disk:
        message = low_disk()
        if message:
            return _skipped_log(sync_type, trigger, message)
    if not active_run(sync_type):
        return None
    return _skipped_log(sync_type, trigger, f"Skipped: another {sync_type} sync is already running.")
