from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote_plus, urlencode

import httpx

from ..config import Settings, get_settings


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


class InvalidProviderSignature(ValueError):
    pass


@dataclass(frozen=True)
class CheckoutResult:
    provider_intent_id: str
    checkout_url: str
    status: str = "created"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundResult:
    provider_refund_id: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderEvent:
    event_id: str
    event_type: str
    status: str
    provider_intent_id: str | None
    order_id: str | None
    amount: int | None
    currency: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderPaymentState:
    provider_intent_id: str
    status: str
    amount: int | None
    currency: str | None
    payload: dict[str, Any]


class PaymentProvider(Protocol):
    name: str

    def create_checkout(
        self,
        *,
        order_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        description: str,
        customer_email: str,
        client_ip: str | None = None,
    ) -> CheckoutResult: ...

    def parse_webhook(self, *, raw_body: bytes, payload: dict[str, Any], signature: str) -> ProviderEvent: ...

    def refund(
        self,
        *,
        provider_intent_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        reason: str,
        metadata: dict[str, Any],
    ) -> RefundResult: ...

    def fetch_payment(self, provider_intent_id: str, *, order_id: str | None = None) -> ProviderPaymentState: ...


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_local(payload: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), _json_bytes(payload), hashlib.sha256).hexdigest()


def verify_local(payload: dict[str, Any], signature: str, secret: str) -> bool:
    return bool(signature) and hmac.compare_digest(sign_local(payload, secret), signature)


def vnpay_signature(params: dict[str, Any], secret: str) -> str:
    clean = {
        key: str(value)
        for key, value in params.items()
        if key not in {"vnp_SecureHash", "vnp_SecureHashType"} and value not in (None, "")
    }
    canonical = urlencode(sorted(clean.items()), quote_via=quote_plus)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()


def stripe_signature(payload: bytes | str, timestamp: int, secret: str) -> str:
    raw = payload if isinstance(payload, bytes) else payload.encode()
    return hmac.new(secret.encode(), str(timestamp).encode() + b"." + raw, hashlib.sha256).hexdigest()


def _request_json(
    method: str,
    url: str,
    *,
    timeout: int,
    headers: dict[str, str] | None = None,
    data: Any = None,
    json_body: Any = None,
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.request(method, url, headers=headers, data=data, json=json_body)
    except httpx.HTTPError as exc:
        raise ProviderRequestError(f"Provider request failed: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:1000]
        raise ProviderRequestError(f"Provider returned HTTP {response.status_code}: {detail}")
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderRequestError("Provider returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise ProviderRequestError("Provider returned an unexpected payload")
    return body


class LocalProvider:
    name = "local"

    def __init__(self, settings: Settings):
        if not settings.fixtures_allowed:
            raise ProviderConfigurationError("Local payment provider is disabled outside development/test")
        self.settings = settings
        self.secret = settings.payment_webhook_secret or settings.secret_key

    def create_checkout(self, **kwargs: Any) -> CheckoutResult:
        provider_id = f"local_{secrets.token_hex(12)}"
        return CheckoutResult(
            provider_intent_id=provider_id,
            checkout_url=f"{self.settings.site_url}/payments/sandbox/local/{provider_id}",
            payload={"fixture": True, "order_id": kwargs["order_id"]},
        )

    def parse_webhook(self, *, raw_body: bytes, payload: dict[str, Any], signature: str) -> ProviderEvent:
        signed_payload = {key: value for key, value in payload.items() if key != "event_id"}
        if not verify_local(signed_payload, signature, self.secret):
            raise InvalidProviderSignature("Invalid local webhook signature")
        return ProviderEvent(
            event_id=str(payload.get("event_id") or payload.get("provider_event_id") or secrets.token_hex(16)),
            event_type="payment.updated",
            status=str(payload.get("status", "paid")),
            provider_intent_id=payload.get("provider_intent_id") or payload.get("intent_id"),
            order_id=payload.get("order_id"),
            amount=int(payload["amount"]) if payload.get("amount") is not None else None,
            currency=str(payload.get("currency", "VND")).upper(),
            payload=payload,
        )

    def refund(self, **kwargs: Any) -> RefundResult:
        refund_id = f"local_refund_{secrets.token_hex(12)}"
        return RefundResult(refund_id, "succeeded", {"fixture": True, **kwargs["metadata"]})

    def fetch_payment(self, provider_intent_id: str, *, order_id: str | None = None) -> ProviderPaymentState:
        return ProviderPaymentState(provider_intent_id, "unknown", None, "VND", {"fixture": True})


class StripeProvider:
    name = "stripe"

    def __init__(self, settings: Settings):
        if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
            raise ProviderConfigurationError("STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required")
        self.settings = settings
        self.base = settings.stripe_api_base.rstrip("/")
        self.auth = {"Authorization": f"Bearer {settings.stripe_secret_key}"}

    def create_checkout(
        self,
        *,
        order_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        description: str,
        customer_email: str,
        client_ip: str | None = None,
    ) -> CheckoutResult:
        data = {
            "mode": "payment",
            "success_url": f"{self.settings.site_url}/payments/return?provider=stripe&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{self.settings.site_url}/payments/return?provider=stripe&cancelled=1",
            "customer_email": customer_email,
            "client_reference_id": order_id,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount),
            "line_items[0][price_data][product_data][name]": description,
            "metadata[order_id]": order_id,
            "payment_intent_data[metadata][order_id]": order_id,
        }
        body = _request_json(
            "POST",
            f"{self.base}/v1/checkout/sessions",
            timeout=self.settings.provider_http_timeout_seconds,
            headers={**self.auth, "Idempotency-Key": idempotency_key},
            data=data,
        )
        session_id = str(body.get("id") or "")
        checkout_url = str(body.get("url") or "")
        if not session_id or not checkout_url:
            raise ProviderRequestError("Stripe checkout response is missing id or url")
        return CheckoutResult(session_id, checkout_url, str(body.get("status") or "open"), body)

    def _verify_signature(self, raw_body: bytes, signature: str) -> None:
        parts: dict[str, list[str]] = {}
        for item in signature.split(","):
            key, _, value = item.partition("=")
            parts.setdefault(key.strip(), []).append(value.strip())
        try:
            timestamp = int(parts["t"][0])
        except (KeyError, ValueError, IndexError) as exc:
            raise InvalidProviderSignature("Malformed Stripe-Signature header") from exc
        if abs(int(time.time()) - timestamp) > self.settings.stripe_webhook_tolerance_seconds:
            raise InvalidProviderSignature("Stripe webhook timestamp is outside tolerance")
        expected = stripe_signature(raw_body, timestamp, self.settings.stripe_webhook_secret)
        if not any(hmac.compare_digest(expected, candidate) for candidate in parts.get("v1", [])):
            raise InvalidProviderSignature("Invalid Stripe webhook signature")

    def parse_webhook(self, *, raw_body: bytes, payload: dict[str, Any], signature: str) -> ProviderEvent:
        self._verify_signature(raw_body, signature)
        event_type = str(payload.get("type") or "unknown")
        obj = ((payload.get("data") or {}).get("object") or {})
        if not isinstance(obj, dict):
            obj = {}
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        status_map = {
            "checkout.session.completed": "paid" if obj.get("payment_status") == "paid" else "processing",
            "checkout.session.async_payment_succeeded": "paid",
            "checkout.session.async_payment_failed": "failed",
            "payment_intent.succeeded": "paid",
            "payment_intent.payment_failed": "failed",
            "payment_intent.canceled": "cancelled",
            "charge.refunded": "refunded",
        }
        provider_intent_id = obj.get("payment_intent") or obj.get("id")
        amount = obj.get("amount_total")
        if amount is None:
            amount = obj.get("amount_received") or obj.get("amount")
        return ProviderEvent(
            event_id=str(payload.get("id") or ""),
            event_type=event_type,
            status=status_map.get(event_type, str(obj.get("status") or "ignored")),
            provider_intent_id=str(provider_intent_id) if provider_intent_id else None,
            order_id=str(metadata.get("order_id") or obj.get("client_reference_id") or "") or None,
            amount=int(amount) if amount is not None else None,
            currency=str(obj.get("currency") or "").upper() or None,
            payload=payload,
        )

    def refund(
        self,
        *,
        provider_intent_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        reason: str,
        metadata: dict[str, Any],
    ) -> RefundResult:
        data: dict[str, str] = {
            "payment_intent": provider_intent_id,
            "amount": str(amount),
            "metadata[reason]": reason,
        }
        for key, value in metadata.items():
            data[f"metadata[{key}]"] = str(value)
        body = _request_json(
            "POST",
            f"{self.base}/v1/refunds",
            timeout=self.settings.provider_http_timeout_seconds,
            headers={**self.auth, "Idempotency-Key": idempotency_key},
            data=data,
        )
        refund_id = str(body.get("id") or "")
        if not refund_id:
            raise ProviderRequestError("Stripe refund response is missing id")
        return RefundResult(refund_id, str(body.get("status") or "pending"), body)

    def fetch_payment(self, provider_intent_id: str, *, order_id: str | None = None) -> ProviderPaymentState:
        body = _request_json(
            "GET",
            f"{self.base}/v1/payment_intents/{provider_intent_id}",
            timeout=self.settings.provider_http_timeout_seconds,
            headers=self.auth,
        )
        status = "paid" if body.get("status") == "succeeded" else str(body.get("status") or "unknown")
        return ProviderPaymentState(
            provider_intent_id,
            status,
            int(body["amount_received"]) if body.get("amount_received") is not None else None,
            str(body.get("currency") or "").upper() or None,
            body,
        )


class VNPAYProvider:
    name = "vnpay"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.secret = settings.vnpay_hash_secret or settings.vnpay_webhook_secret
        if not settings.vnpay_tmn_code or not self.secret:
            raise ProviderConfigurationError("VNPAY_TMN_CODE and VNPAY_HASH_SECRET are required")

    def create_checkout(
        self,
        *,
        order_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        description: str,
        customer_email: str,
        client_ip: str | None = None,
    ) -> CheckoutResult:
        if currency.upper() != "VND":
            raise ProviderRequestError("VNPAY only supports VND in this integration")
        now = datetime.now(timezone.utc).astimezone()
        params: dict[str, str] = {
            "vnp_Version": "2.1.0",
            "vnp_Command": "pay",
            "vnp_TmnCode": self.settings.vnpay_tmn_code,
            "vnp_Amount": str(amount * 100),
            "vnp_CurrCode": "VND",
            "vnp_TxnRef": order_id,
            "vnp_OrderInfo": description,
            "vnp_OrderType": "other",
            "vnp_Locale": "vn",
            "vnp_ReturnUrl": self.settings.vnpay_return_url or f"{self.settings.site_url}/payments/return",
            "vnp_IpAddr": client_ip or "127.0.0.1",
            "vnp_CreateDate": now.strftime("%Y%m%d%H%M%S"),
        }
        params["vnp_SecureHash"] = vnpay_signature(params, self.secret)
        return CheckoutResult(
            provider_intent_id=order_id,
            checkout_url=f"{self.settings.vnpay_payment_url}?{urlencode(params, quote_via=quote_plus)}",
            payload={**params, "vnp_SecureHash": "[redacted]"},
        )

    def parse_webhook(self, *, raw_body: bytes, payload: dict[str, Any], signature: str) -> ProviderEvent:
        received = signature or str(payload.get("vnp_SecureHash") or "")
        expected = vnpay_signature(payload, self.secret)
        if not received or not hmac.compare_digest(expected.lower(), received.lower()):
            raise InvalidProviderSignature("Invalid VNPAY signature")
        response_code = str(payload.get("vnp_ResponseCode") or payload.get("status") or "")
        amount_raw = payload.get("vnp_Amount")
        amount = int(amount_raw) // 100 if amount_raw not in (None, "") else None
        transaction_no = str(payload.get("vnp_TransactionNo") or "")
        order_id = str(payload.get("vnp_TxnRef") or payload.get("order_id") or "") or None
        return ProviderEvent(
            event_id=transaction_no or f"vnpay:{order_id}:{payload.get('vnp_PayDate', '')}",
            event_type="payment.updated",
            status="paid" if response_code == "00" else "failed",
            provider_intent_id=order_id,
            order_id=order_id,
            amount=amount,
            currency="VND",
            payload=payload,
        )

    def _signed_api_payload(self, *, request_id: str, command: str, order_id: str, amount: int = 0, transaction_no: str = "", reason: str = "") -> dict[str, Any]:
        now = datetime.now(timezone.utc).astimezone()
        create_date = now.strftime("%Y%m%d%H%M%S")
        secure_raw = "|".join(
            [request_id, "2.1.0", command, self.settings.vnpay_tmn_code, order_id, str(amount * 100), transaction_no, create_date, "127.0.0.1", reason]
        )
        secure_hash = hmac.new(self.secret.encode(), secure_raw.encode(), hashlib.sha512).hexdigest()
        return {
            "vnp_RequestId": request_id,
            "vnp_Version": "2.1.0",
            "vnp_Command": command,
            "vnp_TmnCode": self.settings.vnpay_tmn_code,
            "vnp_TxnRef": order_id,
            "vnp_Amount": amount * 100,
            "vnp_TransactionNo": transaction_no,
            "vnp_OrderInfo": reason,
            "vnp_TransactionDate": create_date,
            "vnp_CreateDate": create_date,
            "vnp_IpAddr": "127.0.0.1",
            "vnp_SecureHash": secure_hash,
        }

    def refund(
        self,
        *,
        provider_intent_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        reason: str,
        metadata: dict[str, Any],
    ) -> RefundResult:
        payload = self._signed_api_payload(
            request_id=idempotency_key[:32],
            command="refund",
            order_id=str(metadata.get("order_id") or provider_intent_id),
            amount=amount,
            transaction_no=str(metadata.get("provider_transaction_no") or ""),
            reason=reason,
        )
        payload["vnp_TransactionType"] = "02" if metadata.get("partial", True) else "03"
        payload["vnp_CreateBy"] = str(metadata.get("approved_by") or "nestora")
        body = _request_json(
            "POST",
            self.settings.vnpay_api_url,
            timeout=self.settings.provider_http_timeout_seconds,
            json_body=payload,
        )
        response_code = str(body.get("vnp_ResponseCode") or "")
        refund_id = str(body.get("vnp_TransactionNo") or payload["vnp_RequestId"])
        return RefundResult(refund_id, "succeeded" if response_code == "00" else "pending", body)

    def fetch_payment(self, provider_intent_id: str, *, order_id: str | None = None) -> ProviderPaymentState:
        request_id = secrets.token_hex(12)
        payload = self._signed_api_payload(
            request_id=request_id,
            command="querydr",
            order_id=order_id or provider_intent_id,
            reason="Nestora reconciliation",
        )
        body = _request_json(
            "POST",
            self.settings.vnpay_api_url,
            timeout=self.settings.provider_http_timeout_seconds,
            json_body=payload,
        )
        response_code = str(body.get("vnp_ResponseCode") or "")
        amount_raw = body.get("vnp_Amount")
        return ProviderPaymentState(
            provider_intent_id,
            "paid" if response_code == "00" else "failed",
            int(amount_raw) // 100 if amount_raw not in (None, "") else None,
            "VND",
            body,
        )


def get_payment_provider(name: str, settings: Settings | None = None) -> PaymentProvider:
    settings = settings or get_settings()
    normalized = name.strip().lower()
    if normalized == "local":
        return LocalProvider(settings)
    if normalized == "stripe":
        return StripeProvider(settings)
    if normalized == "vnpay":
        return VNPAYProvider(settings)
    raise ProviderConfigurationError(f"Unsupported payment provider: {name}")
