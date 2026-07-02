frappe.ui.form.on("Cloudstore Connector Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "alaiy_os_cloudstore_connector.api.test_connection.test_connection",
				callback(r) {
					const res = r.message || {};
					if (res.success) {
						frappe.show_alert({ message: res.message || __("Connected successfully"), indicator: "green" }, 5);
					} else {
						frappe.show_alert({ message: res.message || __("Connection failed"), indicator: "red" }, 7);
					}
				},
			});
		}, __("Actions"));
	},
});
