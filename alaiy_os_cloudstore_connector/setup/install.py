import frappe


def sync_connector_registry():
    """
    Register or update this connector's row in alaiy_os_core's OS Connector Registry.

    Called from hooks.py → after_migrate, so it runs on every bench migrate.
    Safe to call multiple times — upserts by connector_id (= doc.name).

    Skips silently if alaiy_os_core is not yet migrated (DocType absent).
    """
    if not frappe.db.exists("DocType", "OS Connector Registry"):
        return

    from alaiy_os_cloudstore_connector.connector_meta import connector_meta

    connector_id = connector_meta["connector_id"]

    if frappe.db.exists("OS Connector Registry", connector_id):
        doc = frappe.get_doc("OS Connector Registry", connector_id)
    else:
        doc = frappe.new_doc("OS Connector Registry")

    for key, val in connector_meta.items():
        doc.set(key, val)

    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    frappe.db.commit()
