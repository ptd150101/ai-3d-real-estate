from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

from app.config import Settings
from app.models import MLArtifact, MLDeployment, MLModelVersion, Organization
from app.services.model_runtime import select_runtime
from app.services.payment_providers import (
    InvalidProviderSignature,
    LocalProvider,
    ProviderConfigurationError,
    StripeProvider,
    VNPAYProvider,
    stripe_signature,
    vnpay_signature,
)
from app.services.push_notifications import is_expo_push_token


def test_production_configuration_rejects_fixture_execution():
    settings = Settings(
        environment="production",
        secret_key="x" * 40,
        allow_fixture_providers=True,
        reconstruction_backend="fixture",
        signature_provider="local",
    )
    with pytest.raises(RuntimeError, match="ALLOW_FIXTURE_PROVIDERS"):
        settings.validate_production()
    with pytest.raises(ProviderConfigurationError):
        LocalProvider(settings)


def test_stripe_verifies_raw_body_timestamp_and_amount():
    settings = Settings(
        stripe_secret_key="sk_test_fixture",
        stripe_webhook_secret="whsec_fixture",
        stripe_webhook_tolerance_seconds=300,
    )
    provider = StripeProvider(settings)
    payload = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_1",
                "payment_intent": "pi_1",
                "payment_status": "paid",
                "amount_total": 125000,
                "currency": "vnd",
                "client_reference_id": "order-1",
                "metadata": {"order_id": "order-1"},
            }
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = stripe_signature(raw, timestamp, settings.stripe_webhook_secret)
    event = provider.parse_webhook(
        raw_body=raw,
        payload=payload,
        signature=f"t={timestamp},v1={signature}",
    )
    assert event.status == "paid"
    assert event.provider_intent_id == "pi_1"
    assert event.order_id == "order-1"
    assert event.amount == 125000
    with pytest.raises(InvalidProviderSignature):
        provider.parse_webhook(raw_body=raw + b" ", payload=payload, signature=f"t={timestamp},v1={signature}")


def test_vnpay_signature_and_webhook_normalization():
    settings = Settings(vnpay_tmn_code="DEMO", vnpay_hash_secret="secret")
    provider = VNPAYProvider(settings)
    payload = {
        "vnp_TxnRef": "order-1",
        "vnp_TransactionNo": "123456",
        "vnp_ResponseCode": "00",
        "vnp_Amount": "100000000",
        "vnp_CurrCode": "VND",
    }
    signature = vnpay_signature(payload, settings.vnpay_hash_secret)
    event = provider.parse_webhook(raw_body=b"", payload=payload, signature=signature)
    assert event.status == "paid"
    assert event.amount == 1_000_000
    assert event.order_id == "order-1"


def test_weighted_model_routing_is_sticky(client):
    from conftest import TestingSessionLocal

    db = TestingSessionLocal()
    organization_id = db.scalar(__import__("sqlalchemy").select(Organization).limit(1)).id
    first_artifact = MLArtifact(
        organization_id=organization_id,
        kind="model",
        uri="https://models.example/valuation-v1",
        sha256=uuid.uuid4().hex * 2,
        metadata_json={"endpoint": "https://models.example/valuation-v1"},
    )
    second_artifact = MLArtifact(
        organization_id=organization_id,
        kind="model",
        uri="https://models.example/valuation-v2",
        sha256=uuid.uuid4().hex * 2,
        metadata_json={"endpoint": "https://models.example/valuation-v2"},
    )
    db.add_all([first_artifact, second_artifact])
    db.flush()
    first = MLModelVersion(
        organization_id=organization_id,
        name="valuation",
        task="valuation",
        version="v1",
        status="production",
        artifact_id=first_artifact.id,
    )
    second = MLModelVersion(
        organization_id=organization_id,
        name="valuation",
        task="valuation",
        version="v2",
        status="production",
        artifact_id=second_artifact.id,
    )
    db.add_all([first, second])
    db.flush()
    db.add_all(
        [
            MLDeployment(model_version_id=first.id, environment="production", status="active", traffic_percent=80),
            MLDeployment(model_version_id=second.id, environment="production", status="active", traffic_percent=20),
        ]
    )
    db.commit()
    one = select_runtime(
        db,
        task="valuation",
        organization_id=organization_id,
        routing_key="same-user-and-request",
    )
    two = select_runtime(
        db,
        task="valuation",
        organization_id=organization_id,
        routing_key="same-user-and-request",
    )
    assert one and two
    assert one.deployment.id == two.deployment.id
    db.close()


def test_expo_push_token_validation():
    assert is_expo_push_token("ExponentPushToken[fixture]")
    assert is_expo_push_token("ExpoPushToken[fixture]")
    assert not is_expo_push_token("not-a-token")


def test_historical_migrations_do_not_call_create_all():
    migration_dir = Path(__file__).parents[1] / "alembic" / "versions"
    for migration in migration_dir.glob("*.py"):
        assert "metadata.create_all" not in migration.read_text(encoding="utf-8")
