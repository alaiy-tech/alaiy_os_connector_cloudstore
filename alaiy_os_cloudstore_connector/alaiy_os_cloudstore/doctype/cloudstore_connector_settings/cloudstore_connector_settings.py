import frappe
from frappe.model.document import Document


class CloudstoreConnectorSettings(Document):
    def validate(self):
        old_enabled = frappe.db.get_single_value(
            "Cloudstore Connector Settings", "is_enabled"
        ) or 0
        if self.is_enabled and not old_enabled:
            self._run_setup()
        self._sync_registry_is_enabled()

    def _run_setup(self):
        from alaiy_os_cloudstore_connector.setup.install import (
            setup_custom_fields,
            setup_item_attributes,
            create_default_supplier,
            create_default_price_lists,
        )
        setup_custom_fields()
        setup_item_attributes()
        create_default_supplier()
        create_default_price_lists()

    def _sync_registry_is_enabled(self):
        if frappe.db.exists("OS Connector Registry", "cloudstore"):
            frappe.db.set_value(
                "OS Connector Registry", "cloudstore", "is_enabled", self.is_enabled
            )
