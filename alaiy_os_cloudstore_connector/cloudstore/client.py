# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import requests
import frappe


class CloudstoreClient:
    """
    Thin HTTP client for the Cloudstore API.

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

    # ------------------------------------------------------------------
    # Low-level GET
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict = None) -> dict | list:
        """
        Send a GET request to api_url + path.

        Args:
            path:   URL path relative to api_url, e.g. "/categories/tree".
            params: Optional query-string parameters dict.

        Returns:
            Parsed JSON response (dict or list).

        Raises:
            RuntimeError: when the server returns a non-2xx status code.
        """
        url = f"{self.api_url}{path}"
        resp = self._session.get(url, params=params, timeout=20)
        if not resp.ok:
            raise RuntimeError(
                f"Cloudstore API error {resp.status_code} for {url}: "
                f"{resp.text[:300]}"
            )
        return resp.json()

    # ------------------------------------------------------------------
    # Paginated GET
    # ------------------------------------------------------------------

    def get_paginated(self, path: str, params: dict = None, page_size: int = None):
        """
        Generator that iterates all pages of a paginated Cloudstore endpoint.

        Yields:
            (content_list, metadata_dict) tuples, one per page.

        Args:
            path:      URL path, e.g. "/items".
            params:    Extra query parameters (merged with pagination params).
            page_size: Items per page — defaults to cs_page_size from settings.
        """
        page_size = page_size or self.page_size
        page_index = 0  # Cloudstore API is 0-indexed: pages 0 … total_pages-1
        base_params = dict(params or {})

        while True:
            page_params = {
                **base_params,
                "_pageSize": page_size,
                "_pageIndex": page_index,
            }
            data = self.get(path, params=page_params)
            metadata = data.get("_metadata", {})
            content = data.get("content", [])

            yield content, metadata

            total_pages = int(metadata.get("total_pages", 1))
            if page_index + 1 >= total_pages:
                break
            page_index += 1
