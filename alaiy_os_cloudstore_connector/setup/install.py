import frappe


def sync_connector_registry():
    """
    Register or update this connector's row in alaiy_os_core's OS Connector Registry.
    Called from hooks.py → after_migrate on every bench migrate.
    """
    setup_custom_fields()
    setup_item_attributes()

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


def setup_custom_fields():
    """Add cs_ custom fields to Item Group and Item if they don't exist yet."""
    item_group_fields = [
        {
            "fieldname": "cs_cloudstore_id",
            "label": "Cloudstore Category ID",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "is_group",
        },
        {
            "fieldname": "cs_external_cat_level",
            "label": "Category Level",
            "fieldtype": "Int",
            "insert_after": "cs_cloudstore_id",
        },
        {
            "fieldname": "cs_cloudstore_source",
            "label": "Cloudstore Source",
            "fieldtype": "Data",
            "insert_after": "cs_external_cat_level",
        },
    ]

    item_fields = [
        {
            "fieldname": "cs_cloudstore_id",
            "label": "Cloudstore Item ID",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "item_code",
        },
        {
            "fieldname": "cs_parent_sku",
            "label": "Cloudstore Parent SKU",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "cs_cloudstore_id",
        },
        {
            "fieldname": "cs_cloudstore_source",
            "label": "Cloudstore Source",
            "fieldtype": "Data",
            "insert_after": "cs_parent_sku",
        },
        {
            "fieldname": "cs_last_synced_at",
            "label": "Last Synced from Cloudstore",
            "fieldtype": "Datetime",
            "insert_after": "cs_cloudstore_source",
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
        cf.module = "Alaiy OS Cloudstore"
        cf.insert(ignore_permissions=True)


def setup_item_attributes():
    """Ensure Size and Color Item Attributes exist for variant creation."""
    for attr_name in ("Size", "Color"):
        if not frappe.db.exists("Item Attribute", attr_name):
            attr = frappe.new_doc("Item Attribute")
            attr.attribute_name = attr_name
            attr.numeric_values = 0
            attr.insert(ignore_permissions=True)
    frappe.db.commit()
