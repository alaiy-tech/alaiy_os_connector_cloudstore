class Inventory:
    """/inventory-catalog: start a session, upload the file, finish."""

    def __init__(self, client):
        self._c = client

    def start(self):
        """Open an import session (no body). 409 when one is already running."""
        return self._c.post("/inventory-catalog/start")

    def upload_page(self, page_id, filename: str, content: bytes):
        """Load one page: multipart form field "file" to /inventory-catalog/{pageId}."""
        return self._c.post(
            f"/inventory-catalog/{page_id}", files={"file": (filename, content)}
        )

    def finish(self):
        """Close the session (no body)."""
        return self._c.post("/inventory-catalog/finished")
