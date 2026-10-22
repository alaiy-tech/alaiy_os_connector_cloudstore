class Categories:
    """/categories"""

    def __init__(self, client):
        self._c = client

    def list(self, page_index: int = 0, page_size: int = 20, sort: str = "_id[ASC]"):
        return self._c.get(
            "/categories",
            {"_pageIndex": page_index, "_pageSize": page_size, "_sort": sort},
        )

    def get(self, category_id: str):
        return self._c.get(f"/categories/{category_id}")

    def roots(self, page_index: int = 0, page_size: int = 20):
        return self._c.get(
            "/categories/roots", {"_pageIndex": page_index, "_pageSize": page_size}
        )

    def tree(self):
        return self._c.get("/categories/tree")

    def children(self, category_id: str, page_index: int = 0, page_size: int = 20):
        return self._c.get(
            f"/categories/{category_id}/children",
            {"_pageIndex": page_index, "_pageSize": page_size},
        )
