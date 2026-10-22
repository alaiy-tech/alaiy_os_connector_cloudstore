class Orders:
    """/orders. Write calls take the order body exactly as Cloudstore documents it."""

    def __init__(self, client):
        self._c = client

    def get(self, order_id: str):
        return self._c.get(f"/orders/{order_id}")

    def find_by_shop_order_id(self, shop_order_id: str):
        return self._c.get("/orders/findByShopOrderId", {"shopOrderId": shop_order_id})

    def list(self, page_index: int = 0, page_size: int = 20, date_from: str = None,
             date_to: str = None, statuses: list = None, search_term: str = None,
             buyer_id: str = None, additional_info_key: str = None,
             additional_info_value: str = None):
        params = {"_pageIndex": page_index, "_pageSize": page_size}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if statuses:
            params["statuses"] = list(statuses)  # repeated query key
        if search_term:
            params["searchTerm"] = search_term
        if buyer_id:
            params["buyerId"] = buyer_id
        if additional_info_key:
            params["additionalInfoKey"] = additional_info_key
        if additional_info_value:
            params["additionalInfoValue"] = additional_info_value
        return self._c.get("/orders/listByFilter", params)

    def create(self, order: dict):
        """order = {"order": {"shop_order_id": ..., "items": [...], ...}}"""
        return self._c.post("/orders", json=order)

    def replace(self, order_id: str, order: dict):
        return self._c.put(f"/orders/{order_id}", json=order)

    def patch(self, order_id: str, fields: dict):
        return self._c.patch(f"/orders/{order_id}", json=fields)

    def delete(self, order_id: str):
        return self._c.delete(f"/orders/{order_id}")
