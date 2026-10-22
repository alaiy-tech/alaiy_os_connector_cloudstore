# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import requests
import frappe

from alaiy_os_connector_cloudstore.cloudstore.endpoints import (
    Categories, Events, Inventory, Items, Orders,
)


class CloudstoreClient:
    """
    HTTP transport for the Cloudstore API.

    Endpoints are grouped per resource in cloudstore/endpoints and reached as
    client.categories / items / orders / events / inventory.

    Reads connection settings from the "Cloudstore Connector Settings" Single
    DocType so credentials are never hard-coded.
    """

    def __init__(self):
        settings = frappe.get_single("Cloudstore Connector Settings")

        api_url = (settings.cs_api_url or "").strip().rstrip("/")
        if not api_url:
            frappe.throw(
                "Cloudstore API URL is not configured.",
                frappe.ValidationError,
            )

        bearer_token = (
            settings.get_password("cs_bearer_token", raise_exception=False)
            if settings.cs_bearer_token
            else None
        )
        if not bearer_token:
            frappe.throw(
                "Cloudstore Bearer Token is not configured.",
                frappe.ValidationError,
            )

        self.api_url = api_url
        self.bearer_token = bearer_token
        self.page_size = int(settings.cs_page_size or 250)
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {self.bearer_token}"}
        )

        # One object per API resource, each wrapping this client's transport.
        self.categories = Categories(self)
        self.items = Items(self)
        self.orders = Orders(self)
        self.events = Events(self)
        self.inventory = Inventory(self)

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def request(self, method: str, path: str, params: dict = None, json=None,
                files: dict = None) -> dict | list:
        """
        Send an HTTP request to api_url + path (or to path itself when it is a
        full URL) and return the parsed JSON body ({} when the body is empty).

        Raises:
            RuntimeError: when the server returns a non-2xx status code.
        """
        url = path if path.startswith("http") else f"{self.api_url}{path}"
        resp = self._session.request(
            method, url, params=params, json=json, files=files, timeout=20
        )
        if not resp.ok:
            raise RuntimeError(
                f"Cloudstore API error {resp.status_code} for {url}: "
                f"{resp.text[:300]}"
            )
        return resp.json() if resp.content else {}

    def get(self, path: str, params: dict = None) -> dict | list:
        """GET api_url + path, e.g. get("/categories/tree")."""
        return self.request("GET", path, params=params)

    def swagger(self) -> dict:
        """The OpenAPI spec of the configured environment."""
        return self.get("/swagger.json")

    def post(self, path: str, json=None, params: dict = None, files: dict = None) -> dict | list:
        """POST with a JSON body (json=) or a multipart upload (files=)."""
        return self.request("POST", path, params=params, json=json, files=files)

    def put(self, path: str, json=None) -> dict | list:
        return self.request("PUT", path, json=json)

    def patch(self, path: str, json=None) -> dict | list:
        return self.request("PATCH", path, json=json)

    def delete(self, path: str) -> dict | list:
        return self.request("DELETE", path)

    # ------------------------------------------------------------------
    # Paginated GET
    # ------------------------------------------------------------------

    def get_paginated(self, path: str, params: dict = None, page_size: int = None):
        """
        Generator that iterates all pages of a paginated Cloudstore endpoint.

        Includes loop detection: if an entire page consists only of SKUs already
        seen on a previous page, the API is looping and we stop early.

        Yields:
            (content_list, metadata_dict) tuples, one per page.
            content_list contains only items not seen on prior pages.

        Args:
            path:      URL path, e.g. "/items".
            params:    Extra query parameters (merged with pagination params).
            page_size: Items per page — defaults to cs_page_size from settings.
        """
        page_size = page_size or self.page_size
        page_index = 0  # Cloudstore API is 0-indexed: pages 0 … total_pages-1
        base_params = dict(params or {})
        seen_skus: set = set()

        while True:
            page_params = {
                **base_params,
                "_pageSize": page_size,
                "_pageIndex": page_index,
            }
            data = self.get(path, params=page_params)
            metadata = data.get("_metadata", {})
            content = data.get("content", [])

            new_items = [item for item in content if item.get("sku") not in seen_skus]

            # If the API returned items but none are new, it's stuck in a loop.
            if content and not new_items:
                frappe.log_error(
                    title="Cloudstore: pagination loop detected",
                    message=f"Page {page_index} returned 0 new SKUs — stopping early.",
                )
                break

            for item in new_items:
                if item.get("sku"):
                    seen_skus.add(item["sku"])

            yield new_items, metadata

            total_pages = int(metadata.get("total_pages", 1))
            if page_index + 1 >= total_pages:
                break
            page_index += 1
