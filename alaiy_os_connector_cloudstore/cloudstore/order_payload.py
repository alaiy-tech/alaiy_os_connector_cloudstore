# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe


def cloudstore_lines(so) -> list:
    """Sales Order lines whose Item came from Cloudstore (Item.supplier_id is set)."""
    item_codes = [row.item_code for row in so.items]
    if not item_codes:
        return []
    from_cloudstore = set(
        frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes], "supplier_id": ["is", "set"]},
            pluck="name",
        )
    )
    return [row for row in so.items if row.item_code in from_cloudstore]


def build_order_payload(so, lines: list) -> dict:
    """
    Cloudstore order body for a Sales Order. shop_order_id is the Sales Order
    name, which is also the key used later to look the order up again.
    """
    net_total = float(so.net_total or 0)
    tax_ratio = (float(so.grand_total or 0) / net_total) if net_total else 1.0

    # Cloudstore accepts only PENDING or CONFIRMED on create.
    status = frappe.db.get_single_value("Cloudstore Connector Settings", "cs_order_push_status") or "PENDING"

    supplier_ids = dict(
        frappe.get_all(
            "Item",
            filters={"name": ["in", [row.item_code for row in lines]]},
            fields=["name", "supplier_id"],
            as_list=True,
        )
    )
    items = []
    for row in lines:
        excl = float(row.net_rate or row.rate or 0)
        items.append({
            "item_id": {"$oid": supplier_ids.get(row.item_code, "")},
            "sku": row.item_code,
            "qty": int(row.qty),
            "price": excl,
            "unit_price_tax_excl": {"amount": excl, "currency": so.currency},
            "unit_price_tax_incl": {"amount": round(excl * tax_ratio, 2), "currency": so.currency},
        })

    return {
        "order": {
            "shop_order_id": so.name,
            "order_status": status,
            "order_dt": {"$date": frappe.utils.get_datetime(so.creation).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
            "buyer_email": so.contact_email or "",
            "buyer_name": so.customer_name or "",
            "items": items,
            "additional_info": {},
            "shipping_info": {"address": _address(so.shipping_address_name or so.customer_address)},
            "billing_info": {"address": _address(so.customer_address)},
        }
    }


def _address(address_name: str) -> dict:
    if not address_name:
        return {}
    a = frappe.db.get_value(
        "Address",
        address_name,
        ["address_line1", "address_line2", "city", "state", "pincode", "phone"],
        as_dict=True,
    )
    if not a:
        return {}
    street = ", ".join(x for x in (a.address_line1, a.address_line2) if x)
    return {
        "street": street,
        "city": a.city or "",
        "state": a.state or "",
        "zip": a.pincode or "",
        "contact1": a.phone or "",
    }
