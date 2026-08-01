from __future__ import annotations

import uuid


def _admin_org(client, admin_headers):
    response = client.get("/api/v1/organizations/me", headers=admin_headers)
    assert response.status_code == 200, response.text
    return response.json()[0]["id"]


def _agent_headers(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "agent@nestora.vn", "password": "test-agent-password"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_private_contract_download_and_signing_token_identity(client, admin_headers, buyer_headers):
    org_id = _admin_org(client, admin_headers)
    document_type = f"secure-agreement-{uuid.uuid4().hex[:8]}"
    policy = client.post(
        "/api/v1/contracts/policies",
        headers=admin_headers,
        json={"document_type": document_type, "approved": True, "jurisdiction": "VN"},
    )
    assert policy.status_code == 200, policy.text

    template = client.post(
        "/api/v1/contracts/templates",
        headers={**admin_headers, "X-Organization-ID": org_id},
        json={
            "name": "Secure agreement",
            "document_type": document_type,
            "content_html": "Signer {{signer}}",
            "allowed_fields": ["signer"],
            "version": 1,
        },
    )
    assert template.status_code == 201, template.text

    envelope = client.post(
        "/api/v1/contracts/envelopes",
        headers={**admin_headers, "X-Organization-ID": org_id},
        json={
            "template_id": template.json()["id"],
            "data": {"signer": "Nestora Admin"},
            "participants": [
                {"email": "admin@nestora.vn", "role": "buyer", "signing_order": 1}
            ],
        },
    )
    assert envelope.status_code == 201, envelope.text
    body = envelope.json()
    assert body["document_url"].startswith("/api/v1/contracts/envelopes/")
    assert "/storage/private/" not in body["document_url"]

    blocked = client.get("/storage/private/contracts/guessed.pdf", headers=admin_headers)
    assert blocked.status_code == 404

    document = client.get(body["document_url"], headers=admin_headers)
    assert document.status_code == 200, document.text
    assert document.headers["content-type"].startswith("application/pdf")
    assert document.headers["cache-control"] == "private, no-store"

    participant_id = body["participants"][0]["id"]
    token_response = client.post(
        f"/api/v1/contracts/envelopes/{body['id']}/participants/{participant_id}/signing-token",
        headers={**admin_headers, "X-Organization-ID": org_id},
    )
    assert token_response.status_code == 200, token_response.text
    signing_token = token_response.json()["signing_token"]

    impersonation = client.post(
        f"/api/v1/contracts/envelopes/{body['id']}/sign",
        headers=buyer_headers,
        json={
            "participant_id": participant_id,
            "signing_token": signing_token,
            "consent": True,
        },
    )
    assert impersonation.status_code == 403

    signed = client.post(
        f"/api/v1/contracts/envelopes/{body['id']}/sign",
        headers=admin_headers,
        json={
            "participant_id": participant_id,
            "signing_token": signing_token,
            "consent": True,
        },
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "completed"

    replay = client.post(
        f"/api/v1/contracts/envelopes/{body['id']}/sign",
        headers=admin_headers,
        json={
            "participant_id": participant_id,
            "signing_token": signing_token,
            "consent": True,
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "completed"

    evidence = client.get(
        f"/api/v1/contracts/envelopes/{body['id']}/evidence",
        headers={**admin_headers, "X-Organization-ID": org_id},
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["object_url"] == body["document_url"]


def test_new_organization_is_initialized_and_invitation_can_be_accepted(client, admin_headers):
    slug = f"secure-org-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/organizations",
        headers=admin_headers,
        json={"name": "Secure Organization", "slug": slug},
    )
    assert created.status_code == 200, created.text
    org_id = created.json()["id"]

    current = client.get(
        "/api/v1/organizations/current",
        headers={**admin_headers, "X-Organization-ID": org_id},
    )
    assert current.status_code == 200, current.text
    assert current.json()["flags"]
    assert current.json()["quotas"]
    assert "*" in current.json()["permissions"]

    invitation = client.post(
        "/api/v1/organizations/invitations",
        headers={**admin_headers, "X-Organization-ID": org_id},
        json={"email": "agent@nestora.vn", "role": "agent"},
    )
    assert invitation.status_code == 200, invitation.text
    assert invitation.json()["invite_token"]

    accepted = client.post(
        "/api/v1/organizations/invitations/accept",
        headers=_agent_headers(client),
        json={"token": invitation.json()["invite_token"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["organization_id"] == org_id

    agent_current = client.get(
        "/api/v1/organizations/current",
        headers={**_agent_headers(client), "X-Organization-ID": org_id},
    )
    assert agent_current.status_code == 200, agent_current.text
    assert "properties.write" in agent_current.json()["permissions"]


def test_tenant_export_uses_authorized_download_endpoint(client, admin_headers):
    org_id = _admin_org(client, admin_headers)
    exported = client.post(
        "/api/v1/organizations/exports",
        headers={**admin_headers, "X-Organization-ID": org_id},
    )
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["url"].startswith("/api/v1/organizations/exports/")
    assert "/storage/private/" not in body["url"]

    downloaded = client.get(
        body["url"],
        headers={**admin_headers, "X-Organization-ID": org_id},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"].startswith("application/json")
    assert downloaded.headers["cache-control"] == "private, no-store"
