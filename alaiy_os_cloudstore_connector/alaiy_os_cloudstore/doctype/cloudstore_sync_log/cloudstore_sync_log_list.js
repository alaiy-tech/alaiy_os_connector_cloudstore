const CLOUDSTORE_SYNC_TYPE_COLORS = {
	categories: "orange",
	items: "blue",
};

const CLOUDSTORE_TRIGGER_COLORS = {
	scheduled: "purple",
	manual: "darkgrey",
};

const CLOUDSTORE_STATUS_COLORS = {
	running: "blue",
	success: "green",
	failed: "red",
	skipped: "yellow",
};

function alaiy_pill(value, colors) {
	if (!value) return "";
	const color = colors[value] || "darkgrey";
	return `<span class="indicator-pill ${color} filterable" data-filter="=,${value}">
		<span>${frappe.utils.escape_html(value)}</span>
	</span>`;
}

frappe.listview_settings["Cloudstore Sync Log"] = {
	get_indicator(doc) {
		const map = {
			running: "blue",
			success: "green",
			failed: "red",
			skipped: "yellow",
		};
		return [__(doc.status), map[doc.status] || "darkgrey", `status,=,${doc.status}`];
	},
	formatters: {
		sync_type: (value) => alaiy_pill(value, CLOUDSTORE_SYNC_TYPE_COLORS),
		trigger: (value) => alaiy_pill(value, CLOUDSTORE_TRIGGER_COLORS),
		status: (value) => alaiy_pill(value, CLOUDSTORE_STATUS_COLORS),
	},
};
