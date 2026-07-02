import frappe


def sync_connector_registry():
    """
    Register or update this connector's row in alaiy_os_core's OS Connector Registry.
    Called from hooks.py -> after_migrate on every bench migrate.

    Setup (custom fields, supplier, price lists) is NOT run here anymore.
    It runs once when the connector is first enabled via the settings form.
    Exception: existing installations are detected and auto-marked as enabled
    so their syncs continue uninterrupted after upgrade.
    """
    _fix_settings_as_single()
    _migrate_set_enabled_if_previously_setup()

    if not frappe.db.exists("DocType", "OS Connector Registry"):
        return

    from alaiy_os_cloudstore_connector.connector_meta import connector_meta

    connector_id = connector_meta["connector_id"]

    if frappe.db.exists("OS Connector Registry", connector_id):
        doc = frappe.get_doc("OS Connector Registry", connector_id)
    else:
        doc = frappe.new_doc("OS Connector Registry")

    RUNTIME_FIELDS = {"connection_status", "last_tested_at"}

    if doc.is_new():
        for key, val in connector_meta.items():
            doc.set(key, val)
        doc.insert(ignore_permissions=True)
    else:
        for key, val in connector_meta.items():
            if key not in RUNTIME_FIELDS:
                doc.set(key, val)
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    _update_alaiy_os_sidebar()


def _migrate_set_enabled_if_previously_setup():
    """
    Backward compat: if the custom fields were already deployed by a prior install,
    mark is_enabled=1 in settings so scheduled syncs keep running after upgrade.
    """
    already_enabled = frappe.db.get_single_value(
        "Cloudstore Connector Settings", "is_enabled"
    )
    if already_enabled:
        return
    if frappe.db.exists("Custom Field", "Item-supplier_id"):
        frappe.db.set_single_value("Cloudstore Connector Settings", "is_enabled", 1)
        frappe.db.commit()


def _update_alaiy_os_sidebar():
    """Re-run alaiy_os_core's sidebar provisioning so the Cloudstore Logs
    link appears in the sidebar after this connector is installed/migrated."""
    try:
        from alaiy_os_core.setup.install import create_or_update_workspace_sidebar
        create_or_update_workspace_sidebar()
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="Cloudstore connector: sidebar update failed",
            message=frappe.get_traceback(),
        )


def setup_custom_fields():
    """Add custom fields to Item Group and Item. Called on first enable."""
    item_group_fields = [
        {
            "fieldname": "supplier_id",
            "label": "Supplier ID",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "is_group",
        },
        {
            "fieldname": "supplier_cat_level",
            "label": "Supplier Category Level",
            "fieldtype": "Int",
            "insert_after": "supplier_id",
        },
    ]

    item_fields = [
        {
            "fieldname": "supplier_id",
            "label": "Supplier ID",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "item_code",
        },
        {
            "fieldname": "sku_parent",
            "label": "SKU Parent",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "supplier_id",
        },
        {
            "fieldname": "mnf_color_code",
            "label": "Manufacturer Color Code",
            "fieldtype": "Data",
            "insert_after": "sku_parent",
        },
        {
            "fieldname": "last_synced_at",
            "label": "Last Synced from Supplier",
            "fieldtype": "Datetime",
            "read_only": 1,
            "insert_after": "mnf_color_code",
        },
    ]

    _ensure_custom_fields("Item Group", item_group_fields)
    _ensure_custom_fields("Item", item_fields)
    frappe.db.commit()


def _ensure_custom_fields(doctype, fields):
    for f in fields:
        key = f"{doctype}-{f['fieldname']}"
        if frappe.db.exists("Custom Field", key):
            continue
        cf = frappe.new_doc("Custom Field")
        cf.dt = doctype
        cf.fieldname = f["fieldname"]
        cf.label = f["label"]
        cf.fieldtype = f["fieldtype"]
        cf.insert_after = f.get("insert_after", "")
        cf.search_index = 1 if f.get("search_index") else 0
        cf.read_only = 1 if f.get("read_only") else 0
        cf.module = "Alaiy OS Cloudstore"
        cf.insert(ignore_permissions=True)


def _fix_settings_as_single():
    """
    Force issingle=1 on Cloudstore Connector Settings.
    Frappe does not auto-convert an existing DocType from table-based to Single
    via bench migrate, so we patch it directly every deploy.
    """
    frappe.db.sql(
        "UPDATE `tabDocType` SET issingle=1 WHERE name='Cloudstore Connector Settings' AND issingle=0"
    )
    frappe.db.commit()


def setup_item_attributes():
    """Ensure Size and Color Item Attributes exist for variant creation."""
    for attr_name in ("Size", "Color"):
        if not frappe.db.exists("Item Attribute", attr_name):
            attr = frappe.new_doc("Item Attribute")
            attr.attribute_name = attr_name
            attr.numeric_values = 0
            attr.insert(ignore_permissions=True)
    frappe.db.commit()


def create_default_supplier():
    """Create a placeholder Supplier record for Cloudstore if it doesn't exist."""
    supplier_name = "Cloudstore (The Corner)"
    group_name = "International Brands"
    if not frappe.db.exists("Supplier Group", group_name):
        sg = frappe.new_doc("Supplier Group")
        sg.supplier_group_name = group_name
        sg.insert(ignore_permissions=True)
    if not frappe.db.exists("Supplier", supplier_name):
        s = frappe.new_doc("Supplier")
        s.supplier_name = supplier_name
        s.supplier_type = "Company"
        s.supplier_group = group_name
        s.insert(ignore_permissions=True)
    frappe.db.commit()


def create_default_price_lists():
    """Create Cloudstore buying and selling price lists if absent."""
    for pl_name, is_buying, is_selling in [
        ("Cloudstore - Buying", 1, 0),
        ("Cloudstore - Selling", 0, 1),
    ]:
        if not frappe.db.exists("Price List", pl_name):
            pl = frappe.new_doc("Price List")
            pl.price_list_name = pl_name
            pl.buying = is_buying
            pl.selling = is_selling
            pl.currency = "INR"
            pl.enabled = 1
            pl.insert(ignore_permissions=True)
    frappe.db.commit()
