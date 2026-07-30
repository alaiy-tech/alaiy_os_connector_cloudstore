frappe.ui.form.on("Cloudstore Connector Settings", {
  refresh(frm) {
    frm.page.set_title(__("Cloudstore Settings"));
    alaiy_os.connector_card.mount(frm, "cloudstore");
    alaiy_os.connector_card.setup_password_reveal(
      frm,
      "cs_bearer_token",
      "cloudstore",
    );

    frm.add_custom_button(
      __("Test Connection"),
      () => {
        frappe.call({
          // Goes through the registry wrapper (not test_connection directly)
          // so a successful test also flips the "Connector Status" card at
          // the top of this form from "Not configured" to "Connected" --
          // calling test_connection directly ran the real check but left
          // OS Connector Registry.connection_status untouched.
          method: "alaiy_os.api.connectors.test_connector",
          args: { connector_id: "cloudstore" },
          callback(r) {
            const res = r.message || {};
            if (res.success) {
              frappe.show_alert(
                {
                  message: res.message || __("Connected successfully"),
                  indicator: "green",
                },
                5,
              );
            } else {
              frappe.show_alert(
                {
                  message: res.message || __("Connection failed"),
                  indicator: "red",
                },
                7,
              );
            }
          },
        });
      },
      __("Actions"),
    );

    frm.add_custom_button(
      __("Sync Category Tree"),
      () => {
        frappe.call({
          method:
            "alaiy_os_connector_cloudstore.api.sync.trigger_categories_sync",
          callback: () =>
            frappe.show_alert(
              { message: __("Category sync queued"), indicator: "blue" },
              5,
            ),
        });
      },
      __("Actions"),
    );

    frm.add_custom_button(
      __("Sync Items"),
      () => {
        frappe.call({
          method: "alaiy_os_connector_cloudstore.api.sync.trigger_items_sync",
          callback: () =>
            frappe.show_alert(
              { message: __("Item sync queued"), indicator: "blue" },
              5,
            ),
        });
      },
      __("Actions"),
    );
  },
});
