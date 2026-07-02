frappe.ui.form.on("Cloudstore Connector Settings", {
	refresh(frm) {
		frm.page.set_title(__("Cloudstore Settings"));
		alaiy_os.connector_card.mount(frm, "cloudstore");
		alaiy_os.connector_card.setup_password_reveal(frm, "cs_bearer_token", "cloudstore");

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

		frm.add_custom_button(__("Sync Category Tree"), () => {
			frappe.call({
				method: "alaiy_os_cloudstore_connector.api.sync.trigger_categories_sync",
				callback: () => frappe.show_alert({ message: __("Category sync queued"), indicator: "blue" }, 5),
			});
		}, __("Actions"));

		frm.add_custom_button(__("Sync Items"), () => {
			frappe.call({
				method: "alaiy_os_cloudstore_connector.api.sync.trigger_items_sync",
				callback: () => frappe.show_alert({ message: __("Item sync queued"), indicator: "blue" }, 5),
			});
		}, __("Actions"));
	},
});
