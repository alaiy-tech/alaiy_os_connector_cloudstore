# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

"""Browse Cloudstore categories level by level (for choosing a category to filter by)."""

from alaiy_os_connector_cloudstore.cloudstore.client import CloudstoreClient


def browse(parent_id: str = None, page_size: int = 100) -> list:
    """Root categories, or the children of parent_id. Returns [{id, name, leaf, parent_id}]."""
    client = CloudstoreClient()
    resp = (
        client.categories.children(parent_id, page_size=page_size)
        if parent_id
        else client.categories.roots(page_size=page_size)
    )
    return [_row(r) for r in resp.get("content") or []]


def get(category_id: str) -> dict:
    """One category by id (single reply: the category sits under "content")."""
    return _row(CloudstoreClient().categories.get(category_id).get("content") or {})


def _row(category: dict) -> dict:
    # name is a LocalizableString: {"locs": {"en": "...", ...}}
    locs = (category.get("name") or {}).get("locs") or {}
    return {
        "id": (category.get("_id") or {}).get("$oid", ""),
        "name": locs.get("en") or next(iter(locs.values()), ""),
        "leaf": category.get("leaf"),
        "parent_id": (category.get("parent_id") or {}).get("$oid", ""),
    }
