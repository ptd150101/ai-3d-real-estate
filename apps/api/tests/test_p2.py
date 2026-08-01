from __future__ import annotations

import json
import uuid

from app.services.p2_payments import sign_local


def _admin_org(client, admin_headers):
    response = client.get('/api/v1/organizations/me', headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()
    return response.json()[0]['id']


def _property(client):
    response = client.get('/api/v1/properties?page_size=1')
    assert response.status_code == 200, response.text
    return response.json()['items'][0]


def _agent_headers(client):
    response = client.post('/api/v1/auth/login', json={'email':'agent@nestora.vn','password':'test-agent-password'})
    assert response.status_code == 200, response.text
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def test_p2_organization_tenant_isolation(client, admin_headers):
    org_id = _admin_org(client, admin_headers)
    current = client.get('/api/v1/organizations/current', headers={**admin_headers, 'X-Organization-ID': org_id})
    assert current.status_code == 200, current.text
    assert current.json()['id'] == org_id
    assert any(flag['key'] == 'payments' and flag['enabled'] for flag in current.json()['flags'])

    slug = f"second-{uuid.uuid4().hex[:8]}"
    created = client.post('/api/v1/organizations', headers=admin_headers, json={'name':'Second Agency','slug':slug})
    assert created.status_code == 200, created.text
    second_id = created.json()['id']
    denied = client.get('/api/v1/organizations/current', headers={**_agent_headers(client), 'X-Organization-ID': second_id})
    assert denied.status_code == 403


def test_p2_payment_refund_and_balanced_ledger(client, admin_headers, buyer_headers):
    org_id = _admin_org(client, admin_headers)
    prop = _property(client)
    key = f"reservation-{uuid.uuid4()}"
    response = client.post('/api/v1/reservations', headers=buyer_headers, json={'property_id':prop['id'],'amount':1_000_000,'provider':'local','idempotency_key':key})
    assert response.status_code == 201, response.text
    data = response.json(); order_id = data['order']['id']; intent_id = data['payment_intent']['id']
    duplicate = client.post('/api/v1/reservations', headers=buyer_headers, json={'property_id':prop['id'],'amount':1_000_000,'provider':'local','idempotency_key':key})
    assert duplicate.status_code == 201
    assert duplicate.json()['order']['id'] == order_id

    webhook_payload = {'intent_id':intent_id,'provider_intent_id':None,'status':'paid','amount':None}
    event_id = f"event-{uuid.uuid4()}"
    signature = sign_local(webhook_payload, 'local')
    paid = client.post('/api/v1/payments/webhooks/local', headers={'X-Signature':signature}, json={'event_id':event_id, **webhook_payload})
    assert paid.status_code == 200, paid.text
    assert paid.json()['status'] == 'paid'
    replay = client.post('/api/v1/payments/webhooks/local', headers={'X-Signature':signature}, json={'event_id':event_id, **webhook_payload})
    assert replay.status_code == 200 and replay.json()['duplicate'] is True

    refund = client.post(f'/api/v1/reservations/{order_id}/refunds', headers=buyer_headers, json={'amount':400_000,'reason':'Buyer changed plan'})
    assert refund.status_code == 201, refund.text
    approved = client.post(f"/api/v1/refunds/{refund.json()['id']}/approve", headers={**admin_headers,'X-Organization-ID':org_id})
    assert approved.status_code == 200, approved.text
    assert approved.json()['order_status'] == 'partially_refunded'
    ledger = client.get('/api/v1/finance/ledger', headers={**admin_headers,'X-Organization-ID':org_id})
    assert ledger.status_code == 200, ledger.text
    assert ledger.json()['balanced'] is True
    assert len(ledger.json()['entries']) == 4
    receipt = client.get(f'/api/v1/reservations/{order_id}/receipt', headers=buyer_headers)
    assert receipt.status_code == 200 and receipt.headers['content-type'].startswith('application/pdf')


def test_p2_contract_evidence_is_immutable(client, admin_headers):
    org_id = _admin_org(client, admin_headers)
    policy = client.post('/api/v1/contracts/policies', headers=admin_headers, json={'document_type':'reservation_agreement','approved':True,'jurisdiction':'VN'})
    assert policy.status_code == 200, policy.text
    template = client.post('/api/v1/contracts/templates', headers={**admin_headers,'X-Organization-ID':org_id}, json={'name':'Reservation agreement','document_type':'reservation_agreement','content_html':'Khách hàng {{buyer_name}} đồng ý giữ chỗ tài sản {{property_title}}.','allowed_fields':['buyer_name','property_title'],'version':1})
    assert template.status_code == 201, template.text
    envelope = client.post('/api/v1/contracts/envelopes', headers={**admin_headers,'X-Organization-ID':org_id}, json={'template_id':template.json()['id'],'data':{'buyer_name':'Nestora Admin','property_title':'Demo property'},'participants':[{'email':'admin@nestora.vn','role':'buyer','signing_order':1}]})
    assert envelope.status_code == 201, envelope.text
    participant_id = envelope.json()['participants'][0]['id']
    signed = client.post(f"/api/v1/contracts/envelopes/{envelope.json()['id']}/sign", headers=admin_headers, json={'participant_id':participant_id,'provider_event_id':f"sig-{uuid.uuid4()}",'consent':True,'metadata':{'ip':'127.0.0.1'}})
    assert signed.status_code == 200, signed.text
    assert signed.json()['status'] == 'completed'
    evidence = client.get(f"/api/v1/contracts/envelopes/{envelope.json()['id']}/evidence", headers={**admin_headers,'X-Organization-ID':org_id})
    assert evidence.status_code == 200, evidence.text
    assert len(evidence.json()['checksum']) == 64
    assert evidence.json()['evidence']['document_checksum'] == envelope.json()['checksum']


def test_p2_valuation_recommendation_and_privacy(client, buyer_headers):
    prop = _property(client)
    valuation = client.post('/api/v1/valuations', headers=buyer_headers, json={'property_id':prop['id']})
    assert valuation.status_code == 201, valuation.text
    body = valuation.json()
    assert body['status'] == 'completed'
    assert body['range']['lower'] < body['estimate'] < body['range']['upper']
    assert body['feature_snapshot']['district']

    recommendations = client.get('/api/v1/recommendations?limit=6', headers=buyer_headers)
    assert recommendations.status_code == 200, recommendations.text
    assert recommendations.json()['items']
    first = recommendations.json()['items'][0]
    hidden = client.post('/api/v1/recommendations/feedback', headers=buyer_headers, json={'property_id':first['property_id'],'action':'hide'})
    assert hidden.status_code == 201
    again = client.get('/api/v1/recommendations?limit=12', headers=buyer_headers)
    assert all(item['property_id'] != first['property_id'] for item in again.json()['items'])
    disabled = client.patch('/api/v1/recommendations/profile', headers=buyer_headers, json={'enabled':False,'reset':True})
    assert disabled.status_code == 200 and disabled.json()['enabled'] is False


def test_p2_reconstruction_review_creates_ar_vr(client, admin_headers):
    org_id = _admin_org(client, admin_headers)
    prop = _property(client)
    session = client.post('/api/v1/captures', headers={**admin_headers,'X-Organization-ID':org_id}, json={'property_id':prop['id'],'capture_type':'images','requirements':{'fixture':True}})
    assert session.status_code == 201, session.text
    sid = session.json()['id']
    uploaded = client.post(f'/api/v1/captures/{sid}/files', headers={**admin_headers,'X-Organization-ID':org_id}, json={'url':'/storage/private/captures/demo.jpg','sha256':uuid.uuid4().hex*2,'mime_type':'image/jpeg','size_bytes':1024,'metadata':{'width':1920,'height':1080}})
    assert uploaded.status_code == 201, uploaded.text
    job = client.post(f'/api/v1/captures/{sid}/reconstruct', headers={**admin_headers,'X-Organization-ID':org_id}, json={'representation':'mesh'})
    assert job.status_code == 202, job.text
    processed = client.post(f"/api/v1/reconstruction-jobs/{job.json()['id']}/run-local", headers={**admin_headers,'X-Organization-ID':org_id})
    assert processed.status_code == 200, processed.text
    reviewed = client.post(f"/api/v1/reconstruction-artifacts/{processed.json()['artifact_id']}/review", headers={**admin_headers,'X-Organization-ID':org_id}, json={'status':'approved','notes':'Fixture passed'})
    assert reviewed.status_code == 200 and reviewed.json()['published'] is True
    immersive = client.get(f"/api/v1/properties/{prop['id']}/immersive")
    assert immersive.status_code == 200, immersive.text
    assert immersive.json()['ar'] and immersive.json()['vr']
    assert immersive.json()['vr']['comfort']['smooth_locomotion'] is False


def test_p2_ml_evaluation_gate_and_rollback(client, admin_headers):
    org_id = _admin_org(client, admin_headers)
    artifact = client.post('/api/v1/mlops/artifacts', headers={**admin_headers,'X-Organization-ID':org_id}, json={'kind':'model','uri':'s3://models/recommendation-v1.bin','sha256':uuid.uuid4().hex*2,'metadata':{'license':'internal'}})
    assert artifact.status_code == 201, artifact.text
    model = client.post('/api/v1/mlops/models', headers={**admin_headers,'X-Organization-ID':org_id}, json={'name':'ranker','task':'recommendation','version':uuid.uuid4().hex[:8],'artifact_id':artifact.json()['id'],'metrics':{'ndcg':0.72}})
    assert model.status_code == 201, model.text
    blocked = client.post(f"/api/v1/mlops/models/{model.json()['id']}/promote", headers={**admin_headers,'X-Organization-ID':org_id}, json={'environment':'production','traffic_percent':100})
    assert blocked.status_code == 409
    evaluation = client.post(f"/api/v1/mlops/models/{model.json()['id']}/evaluations", headers={**admin_headers,'X-Organization-ID':org_id}, json={'dataset_version':'holdout-2026-07','metrics':{'ndcg':0.72},'passed':True,'gate':{'minimum_ndcg':0.65}})
    assert evaluation.status_code == 201
    promoted = client.post(f"/api/v1/mlops/models/{model.json()['id']}/promote", headers={**admin_headers,'X-Organization-ID':org_id}, json={'environment':'production','traffic_percent':20})
    assert promoted.status_code == 200, promoted.text
    rollback = client.post(f"/api/v1/mlops/deployments/{promoted.json()['id']}/rollback", headers={**admin_headers,'X-Organization-ID':org_id})
    assert rollback.status_code == 200 and rollback.json()['status'] == 'rolled_back'


def test_p2_mobile_refresh_rotation_and_offline_dedupe(client):
    login = client.post('/api/v1/mobile/auth/login', json={'email':'buyer@nestora.vn','password':'test-buyer-password','device_id':'test-device-1'})
    assert login.status_code == 200, login.text
    body = login.json(); headers={'Authorization':f"Bearer {body['access_token']}"}
    refresh = client.post('/api/v1/mobile/auth/refresh', json={'refresh_token':body['refresh_token'],'device_id':'test-device-1'})
    assert refresh.status_code == 200, refresh.text
    refreshed = refresh.json()
    replay = client.post('/api/v1/mobile/auth/refresh', json={'refresh_token':body['refresh_token'],'device_id':'test-device-1'})
    assert replay.status_code == 401
    prop = _property(client)
    mutation_id = f"offline-{uuid.uuid4()}"
    payload={'device_id':'test-device-1','client_mutation_id':mutation_id,'mutation_type':'favorite.add','payload':{'property_id':prop['id']}}
    first = client.post('/api/v1/mobile/mutations', headers=headers, json=payload)
    second = client.post('/api/v1/mobile/mutations', headers=headers, json=payload)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()['id'] == second.json()['id']
    bootstrap = client.get('/api/v1/mobile/bootstrap', headers=headers)
    assert bootstrap.status_code == 200 and bootstrap.json()['properties']
    logout = client.post('/api/v1/mobile/auth/logout', headers={'Authorization':f"Bearer {refreshed['access_token']}"}, json={'refresh_token':refreshed['refresh_token'],'device_id':'test-device-1'})
    assert logout.status_code == 200 and logout.json()['revoked'] == 1
    after_logout = client.post('/api/v1/mobile/auth/refresh', json={'refresh_token':refreshed['refresh_token'],'device_id':'test-device-1'})
    assert after_logout.status_code == 401
