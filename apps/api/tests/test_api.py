from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_search_and_detail(client):
    response = client.get("/api/v1/properties", params={"district": "Cầu Giấy", "has_3d": True})
    assert response.status_code == 200
    payload = response.json(); assert payload["total"] >= 1
    detail = client.get(f"/api/v1/properties/{payload['items'][0]['slug']}")
    assert detail.status_code == 200; assert detail.json()["model_3d"]["hotspots"]


def test_natural_search(client):
    response = client.post("/api/v1/properties/parse-search", json={"query": "Tìm nhà Cầu Giấy dưới 13 tỷ ít nhất 3 phòng ngủ có 3D"})
    assert response.status_code == 200
    filters = response.json()["filters"]
    assert filters["max_price"] == 13_000_000_000; assert filters["bedrooms"] == 3; assert filters["has_3d"] is True


def test_auth_and_favorite(client, buyer_headers):
    property_id = client.get("/api/v1/properties").json()["items"][0]["id"]
    assert client.put(f"/api/v1/favorites/{property_id}", headers=buyer_headers).status_code == 204
    favorites = client.get("/api/v1/favorites", headers=buyer_headers)
    assert favorites.status_code == 200; assert any(x["property"]["id"] == property_id for x in favorites.json())


def test_mortgage(client):
    response = client.post("/api/v1/tools/mortgage", json={"property_price": 12_500_000_000, "down_payment_percent": 30, "annual_interest_percent": 9, "term_years": 20})
    assert response.status_code == 200; assert response.json()["monthly_payment"] > 0; assert len(response.json()["schedule_preview"]) == 12


def test_chat_context(client):
    property_id = client.get("/api/v1/properties").json()["items"][0]["id"]
    response = client.post("/api/v1/chat", json={"message": "Căn này giá bao nhiêu?", "context": {"current_property_id": property_id}})
    assert response.status_code == 200; assert "tỷ" in response.json()["message"]; assert response.json()["tool_results"][0]["tool"] == "get_current_property"


def test_appointment(client, buyer_headers):
    property_id = client.get("/api/v1/properties").json()["items"][0]["id"]
    scheduled = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    response = client.post("/api/v1/appointments", headers=buyer_headers, json={"property_id": property_id, "full_name": "Test User", "phone": "0912345678", "scheduled_at": scheduled})
    assert response.status_code == 201, response.text; assert response.json()["status"] == "pending"


def test_admin_permissions_and_dashboard(client, admin_headers, buyer_headers):
    assert client.get("/api/v1/admin/dashboard", headers=buyer_headers).status_code == 403
    response = client.get("/api/v1/admin/dashboard", headers=admin_headers)
    assert response.status_code == 200; assert response.json()["properties_published"] >= 6
