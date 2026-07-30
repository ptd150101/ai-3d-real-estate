from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone


def login(client, email, password):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_p1_notification_saved_search_and_analytics(client, buyer_headers, admin_headers):
    prefs = client.get("/api/v1/notification-preferences", headers=buyer_headers)
    assert prefs.status_code == 200
    updated = client.patch("/api/v1/notification-preferences", headers=buyer_headers, json={"email_enabled": False, "in_app_enabled": True})
    assert updated.status_code == 200 and updated.json()["email_enabled"] is False

    saved = client.post("/api/v1/saved-searches", headers=buyer_headers, json={"name": "Cầu Giấy dưới 15 tỷ", "filters_json": {"district": ["Cầu Giấy"], "max_price": 15_000_000_000}, "notify": True})
    assert saved.status_code == 201, saved.text
    search_id = saved.json()["id"]
    sub = client.put(f"/api/v1/saved-searches/{search_id}/subscription", headers=buyer_headers, json={"frequency": "immediate", "is_active": True, "notify_price_drop": True})
    assert sub.status_code == 200
    run = client.post(f"/api/v1/saved-searches/{search_id}/run", headers=buyer_headers)
    assert run.status_code == 200 and run.json()["new_matches"] >= 1
    matches = client.get(f"/api/v1/saved-searches/{search_id}/matches", headers=buyer_headers)
    assert matches.status_code == 200 and matches.json()

    event = client.post("/api/v1/analytics/events", headers=buyer_headers, json={"anonymous_id": "test-anonymous-123", "event_name": "property_viewed", "dedupe_key": "p1-event-1", "metadata_json": {"email": "must-strip@example.com", "source": "test"}})
    assert event.status_code == 202
    duplicate = client.post("/api/v1/analytics/events", headers=buyer_headers, json={"anonymous_id": "test-anonymous-123", "event_name": "property_viewed", "dedupe_key": "p1-event-1", "metadata_json": {}})
    assert duplicate.status_code == 202 and duplicate.json()["id"] == event.json()["id"]
    dashboard = client.get("/api/v1/admin/analytics/dashboard", headers=admin_headers)
    assert dashboard.status_code == 200


def test_p1_calendar_review_and_messaging(client, buyer_headers):
    agent_headers = login(client, "agent@nestora.vn", "test-agent-password")
    agent_me = client.get("/api/v1/auth/me", headers=agent_headers).json()
    agents = client.get("/api/v1/agents").json()
    agent_id = agents[0]["id"] if isinstance(agents, list) else agents["items"][0]["id"]
    properties = client.get("/api/v1/properties?page_size=1").json()["items"]
    prop = properties[0]

    rule = client.post("/api/v1/agent/availability-rules", headers=agent_headers, json={"weekday": (datetime.now(timezone.utc)+timedelta(days=2)).astimezone().weekday(), "start_minute": 540, "end_minute": 1020, "slot_minutes": 60, "buffer_minutes": 0, "timezone": "UTC", "active": True})
    assert rule.status_code in {201, 400}, rule.text
    slots = client.get(f"/api/v1/agents/{agent_id}/availability?days=7").json()
    available = next(x for x in slots if x["available"])
    booking = client.post("/api/v1/appointments/book", headers=buyer_headers, json={"property_id": prop["id"], "agent_id": agent_id, "start_at": available["start_at"], "full_name": "Nguyễn Minh Anh", "phone": "0912345678", "email": "buyer@nestora.vn"})
    assert booking.status_code == 201, booking.text
    appointment_id = booking.json()["id"]
    duplicate = client.post("/api/v1/appointments/book", headers=buyer_headers, json={"property_id": prop["id"], "agent_id": agent_id, "start_at": available["start_at"], "full_name": "Nguyễn Minh Anh", "phone": "0912345678"})
    assert duplicate.status_code == 409
    completed = client.patch(f"/api/v1/appointments/{appointment_id}/status", headers=agent_headers, json={"status": "completed"})
    assert completed.status_code == 200
    review = client.post("/api/v1/reviews", headers=buyer_headers, json={"appointment_id": appointment_id, "rating": 5, "communication_rating": 5, "knowledge_rating": 5, "responsiveness_rating": 5, "comment": "Tư vấn rõ ràng"})
    assert review.status_code == 201, review.text
    reviews = client.get(f"/api/v1/agents/{agent_id}/reviews")
    assert reviews.status_code == 200 and reviews.json()["total"] >= 1

    thread = client.post("/api/v1/messages/threads", headers=buyer_headers, json={"property_id": prop["id"], "agent_id": agent_id, "subject": "Hỏi căn nhà"})
    assert thread.status_code == 201, thread.text
    thread_id = thread.json()["id"]
    first = client.post(f"/api/v1/messages/threads/{thread_id}/messages", headers=buyer_headers, json={"client_message_id": "client-message-p1-0001", "content": "Căn này còn không?"})
    assert first.status_code == 201
    same = client.post(f"/api/v1/messages/threads/{thread_id}/messages", headers=buyer_headers, json={"client_message_id": "client-message-p1-0001", "content": "Căn này còn không?"})
    assert same.status_code == 201 and same.json()["id"] == first.json()["id"]
    inbox = client.get("/api/v1/messages/threads", headers=agent_headers)
    assert inbox.status_code == 200 and any(x["id"] == thread_id for x in inbox.json())
    token = client.post("/api/v1/messages/socket-token", headers=buyer_headers)
    assert token.status_code == 200 and token.json()["token"]


def test_p1_crm_panorama_legal_and_brochure(client, buyer_headers, admin_headers):
    properties = client.get("/api/v1/properties?page_size=1").json()["items"]
    prop = properties[0]
    connection = client.post("/api/v1/admin/crm/connections", headers=admin_headers, json={"provider": "local", "config_json": {}, "active": True})
    assert connection.status_code == 201
    rule = client.post("/api/v1/admin/crm/routing-rules", headers=admin_headers, json={"name": "Default", "priority": 100, "conditions_json": {}, "strategy": "least_loaded", "active": True})
    assert rule.status_code == 201
    lead = client.post("/api/v1/leads", headers=buyer_headers, json={"property_id": prop["id"], "full_name": "Nguyễn Minh Anh", "phone": "0912345678", "email": "buyer@nestora.vn", "message": "Xin tư vấn", "source": "p1-test"})
    assert lead.status_code == 201 and lead.json()["assigned_agent_id"]

    scene = client.post("/api/v1/admin/panorama/scenes", headers=admin_headers, json={"property_id": prop["id"], "name": "Phòng khách", "image_url": "https://example.com/panorama.jpg", "initial_yaw": 0, "initial_pitch": 0, "initial_fov": 75, "sort_order": 0, "published": True, "metadata_json": {}})
    assert scene.status_code == 201, scene.text
    graph = client.get(f"/api/v1/properties/{prop['id']}/panorama")
    assert graph.status_code == 200 and len(graph.json()["scenes"]) == 1

    detail = client.get(f"/api/v1/properties/{prop['slug']}").json()
    document_id = detail["documents"][0]["id"]
    version = client.post("/api/v1/admin/legal/versions", headers=admin_headers, json={"property_document_id": document_id, "storage_key": "/tmp/demo-legal.pdf", "source_url": "https://example.com/legal.pdf", "checksum_sha256": hashlib.sha256(b"legal").hexdigest(), "content_type": "application/pdf", "size_bytes": 5})
    assert version.status_code == 201, version.text
    approved = client.post(f"/api/v1/admin/legal/versions/{version.json()['id']}/review", headers=admin_headers, json={"decision": "approved", "notes": "verified"})
    assert approved.status_code == 200 and approved.json()["active"] is True
    buyer = client.get("/api/v1/auth/me", headers=buyer_headers).json()
    grant = client.post("/api/v1/admin/legal/grants", headers=admin_headers, json={"version_id": version.json()["id"], "user_id": buyer["id"], "expires_minutes": 15, "max_downloads": 1})
    assert grant.status_code == 201 and grant.json()["token"]

    brochure = client.post(f"/api/v1/properties/{prop['id']}/brochure", json={"template_version": "v1", "force": False})
    assert brochure.status_code == 200 and brochure.json()["status"] in {"queued", "ready"}
