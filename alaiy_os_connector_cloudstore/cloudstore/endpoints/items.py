class Items:
    """/items (v1) and the v2 parent filter."""

    def __init__(self, client):
        self._c = client

    def paginated(self, with_quantities: bool = True):
        """Generator over every item, page by page (CloudstoreClient.get_paginated)."""
        params = {"withQuantities": "true"} if with_quantities else {}
        return self._c.get_paginated("/items", params=params)

    # customer_id (optional on every read below): Cloudstore then adds an
    # additional_info block with that customer's own price (customer_price).

    def get(self, item_id: str, customer_id: str = None):
        return self._c.get(f"/items/{item_id}", _customer(customer_id))

    def find_by_code(self, code: str, code_type: str = "SKU", customer_id: str = None):
        """code_type: BARCODE, BARCODES, EAN, ITEM_ID, MNF_CODE, MPN, NS_INTERNAL_ID, SKU, SKU_PARENT, UPC."""
        return self._c.get("/items/findByCode", {"type": code_type, "code": code, **_customer(customer_id)})

    def list_by_code(self, code: str, code_type: str = "SKU", search_type: str = None,
                     page_index: int = 0, page_size: int = 50, customer_id: str = None):
        """search_type: EXACT, PARTIAL_CASE_SENSITIVE, PARTIAL_CASE_INSENSITIVE (server default)."""
        params = {"type": code_type, "code": code, "_pageIndex": page_index, "_pageSize": page_size}
        if search_type:
            params["_searchType"] = search_type
        return self._c.get("/items/listByCode", {**params, **_customer(customer_id)})

    def search(self, term: str, page_size: int = 50, customer_id: str = None):
        """Matches SKU, barcode, title, description, brand or season. Max page size 250."""
        return self._c.get(
            "/items/listBySearchTerm",
            {"searchTerm": term, "_pageSize": page_size, **_customer(customer_id)},
        )

    def list_by_parent_skus(self, parent_skus: list, customer_id: str = None):
        """POST used as a query: every variant of the given parent SKUs."""
        return self._c.post(
            "/items/listByParentSKUList", json=list(parent_skus), params=_customer(customer_id) or None
        )

    def list_by_category_brand_season(self, category_id: str, brand: str = None,
                                      season: str = None, with_quantities: bool = True):
        """In the Postman collection, not in the API spec: unverified."""
        params = {
            "categoryId": category_id,
            "withQuantities": str(with_quantities).lower(),
        }
        if brand:
            params["brand"] = brand
        if season:
            params["season"] = season
        return self._c.get("/items/listByCategoryAndBrandAndSeason", params)

    def list_parents_by_filter(self, filters: dict, page_index: int = 0,
                               page_size: int = 20, with_quantities: bool = True):
        """
        v2: reply content is [{"parent_sku": ..., "items": [ShopItem]}]. The
        filter is required but may be {}; fields are brands, cat_ids, whs_ids
        (each {"values": [...], "op": "IN"}).
        """
        url = self._c.api_url.replace("/v1", "/v2", 1) + "/items/listParentsByFilter"
        return self._c.post(
            url,
            json=filters,
            params={
                "_pageIndex": page_index,
                "_pageSize": page_size,
                "withQuantities": str(with_quantities).lower(),
            },
        )


def _customer(customer_id):
    return {"customerId": customer_id} if customer_id else {}
