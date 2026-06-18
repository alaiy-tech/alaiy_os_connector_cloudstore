import frappe


def test_connection():
    """
    Verify that the saved credentials can reach the Cloudstore API.
    Calls GET /shop/v1/categories/roots — lightweight, auth-required endpoint.
    Returns: {"success": bool, "message": str}
    """
    doc = frappe.get_single("Cloudstore Connector Settings")
    api_url = (doc.cs_api_url or "").strip().rstrip("/")
    bearer_token = doc.get_password("cs_bearer_token") if doc.cs_bearer_token else None

    if not api_url:
        return {"success": False, "message": "API URL is not set."}
    if not bearer_token:
        return {"success": False, "message": "Bearer Token is not set."}

    import requests

    url = f"{api_url}/shop/v1/categories/roots"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"success": True, "message": f"Connected successfully ({resp.status_code})"}
        elif resp.status_code == 401:
            return {"success": False, "message": "Authentication failed — check your Bearer Token."}
        elif resp.status_code == 403:
            return {"success": False, "message": "Access forbidden — verify your shop credentials."}
        else:
            return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": f"Could not connect to {api_url}. Check the API URL."}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Request timed out (10s)."}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}
