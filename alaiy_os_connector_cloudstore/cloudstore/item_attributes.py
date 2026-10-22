# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import json

_LOCALE_KEYS = ("size_conversion", "color", "made", "sex", "care")


def build_supplier_attributes(item_data: dict, mnf_color_code: str) -> dict:
    """
    Everything Cloudstore returns for an item that has no native Item field,
    flattened to {key: text} for the Item Supplier Attribute table.

    - every entry of props, under its own key (so new Cloudstore props are kept)
    - English text of title, desc, color, made, sex, care, size_conversion
    - composition as "100% Calfskin", materials, all category ids
    - source update time, image placement, warehouse reservations
    - abs, bc, linked_items, external_identifiers, search_tags, pb as JSON text
    """
    props = item_data.get("props") or {}
    singles = (item_data.get("locs") or {}).get("singles") or {}
    lists = (item_data.get("locs") or {}).get("lists") or {}

    attrs = {key: props[key] for key in props}
    attrs["mnf_color_code"] = mnf_color_code

    attrs["title_en"] = _en(singles.get("title"))
    attrs["desc_en"] = _en(singles.get("desc"))
    for key in _LOCALE_KEYS:
        attrs[f"{key}_en"] = _en(singles.get(key))

    attrs["composition"] = ", ".join(
        f"{c.get('perc')}% {_en(c.get('material'))}".strip()
        + (f" ({c['part']})" if c.get("part") and c["part"] != "GENERAL" else "")
        for c in (item_data.get("composition") or [])
    )
    attrs["materials"] = ", ".join(_en(m) for m in (lists.get("materials") or []))

    attrs["category_ids"] = ", ".join(
        (c or {}).get("$oid", "") for c in (item_data.get("cats") or [])
    )
    # Other ShopItem fields: stored as JSON text, only when Cloudstore sends them.
    for key in ("abs", "bc", "linked_items", "external_identifiers", "search_tags", "pb"):
        value = item_data.get(key)
        if value:
            attrs[key] = json.dumps(value, ensure_ascii=False)

    attrs["source_updated_at"] = (item_data.get("lst_info_update_dt") or {}).get("$date", "")

    imgs = sorted(item_data.get("imgs") or [], key=lambda x: x.get("pos", 99))
    attrs["image_placement"] = json.dumps(
        [{"pos": i.get("pos"), "placement": i.get("placement"), "excluded_shops": i.get("excluded_shops")}
         for i in imgs if i.get("placement") or i.get("excluded_shops")]
    )

    reservations = [
        {"wh_id": (w.get("wh_id") or {}).get("$oid"), "shops_reservation": w["shops_reservation"]}
        for w in (item_data.get("whs") or []) if w.get("shops_reservation")
    ]
    attrs["shops_reservation"] = json.dumps(reservations) if reservations else ""

    return {k: v for k, v in attrs.items() if v not in (None, "", "[]")}


def _en(locale_dict) -> str:
    """English value of a {lang: value} dict, else any first value."""
    if not isinstance(locale_dict, dict):
        return ""
    return locale_dict.get("en") or next(iter(locale_dict.values()), "") or ""
