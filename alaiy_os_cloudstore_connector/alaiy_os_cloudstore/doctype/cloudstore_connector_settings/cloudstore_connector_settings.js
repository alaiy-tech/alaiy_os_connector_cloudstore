frappe.ui.form.on("Cloudstore Connector Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "alaiy_os_cloudstore_connector.api.test_connection.test_connection",
				callback(r) {
					const res = r.message || {};
					if (res.success) {
						frappe.msgprint({ title: __("Connected"), indicator: "green", message: res.message });
					} else {
						frappe.msgprint({ title: __("Connection Failed"), indicator: "red", message: res.message });
					}
				},
			});
		}, __("Actions"));
	},
});
