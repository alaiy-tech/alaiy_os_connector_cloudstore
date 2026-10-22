class Events:
    """/events"""

    def __init__(self, client):
        self._c = client

    def next_page(self):
        """
        GET /events: "Get next events page". The API has no paging or type
        parameters, so each call is expected to move a server-side position
        forward. Treat what it returns as consumed and process it right away.
        """
        return self._c.get("/events")

    def create(self, event: dict):
        """
        SANDBOX ONLY: Cloudstore answers 403 for this call in production.

        PersonalShopEventCreationRequest: type, items [{item_id, qty, order_id,
        stock_price, sale_price}], order_id, shipment_id. e.g.
        {"type": "ITEMS_AVAILABILITY_AND_PRICE_UPDATED",
         "items": [{"item_id": {"$oid": "..."}, "qty": 1,
                    "stock_price": 1.0, "sale_price": 1.0}]}
        """
        return self._c.post("/events", json=event)
