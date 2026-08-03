from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ..config import Settings, get_settings


class SignatureProviderConfigurationError(RuntimeError):
    pass


class SignatureProviderRequestError(RuntimeError):
    pass


class InvalidSignatureWebhook(ValueError):
    pass


@dataclass(frozen=True)
class ProviderEnvelope:
    envelope_id: str
    status: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderRecipientView:
    url: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderSignatureEvent:
    event_id: str
    envelope_id: str
    email: str | None
    recipient_id: str | None
    status: str
    payload: dict[str, Any]


class SignatureProvider(Protocol):
    name: str

    def create_envelope(
        self,
        *,
        document_name: str,
        document_bytes: bytes,
        subject: str,
        participants: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> ProviderEnvelope: ...

    def create_recipient_view(
        self,
        *,
        provider_envelope_id: str,
        participant: dict[str, Any],
        return_url: str,
    ) -> ProviderRecipientView: ...

    def parse_webhook(self, *, raw_body: bytes, payload: dict[str, Any], signature: str) -> list[ProviderSignatureEvent]: ...


def _json_request(
    method: str,
    url: str,
    *,
    settings: Settings,
    token: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.provider_http_timeout_seconds, follow_redirects=False) as client:
            response = client.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise SignatureProviderRequestError(f"Signature provider request failed: {exc}") from exc
    if response.status_code >= 400:
        raise SignatureProviderRequestError(
            f"Signature provider returned HTTP {response.status_code}: {response.text[:1000]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SignatureProviderRequestError("Signature provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SignatureProviderRequestError("Signature provider returned an unexpected payload")
    return payload


class LocalSignatureProvider:
    name = "local"

    def __init__(self, settings: Settings):
        if not settings.fixtures_allowed:
            raise SignatureProviderConfigurationError("Local signature provider is disabled in production")

    def create_envelope(self, **_: Any) -> ProviderEnvelope:
        return ProviderEnvelope("local", "sent", {"fixture": True})

    def create_recipient_view(self, **_: Any) -> ProviderRecipientView:
        raise SignatureProviderRequestError("Local signing uses the Nestora signing-token endpoint")

    def parse_webhook(self, **_: Any) -> list[ProviderSignatureEvent]:
        raise InvalidSignatureWebhook("Local signing does not accept provider webhooks")


class DocuSignProvider:
    name = "docusign"

    def __init__(self, settings: Settings):
        required = {
            "DOCUSIGN_ACCOUNT_ID": settings.docusign_account_id,
            "DOCUSIGN_ACCESS_TOKEN": settings.docusign_access_token,
            "DOCUSIGN_WEBHOOK_HMAC_SECRET": settings.docusign_webhook_hmac_secret,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise SignatureProviderConfigurationError("Missing " + ", ".join(missing))
        self.settings = settings
        self.base = settings.docusign_base_url.rstrip("/")

    def create_envelope(
        self,
        *,
        document_name: str,
        document_bytes: bytes,
        subject: str,
        participants: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> ProviderEnvelope:
        signers: list[dict[str, Any]] = []
        for index, participant in enumerate(participants, 1):
            recipient_id = str(participant.get("id") or index)
            signer: dict[str, Any] = {
                "email": participant["email"],
                "name": participant.get("name") or participant["email"],
                "recipientId": recipient_id,
                "routingOrder": str(participant.get("signing_order") or index),
                "tabs": {
                    "signHereTabs": [
                        {
                            "anchorString": participant.get("anchor") or "[[SIGN_HERE]]",
                            "anchorUnits": "pixels",
                            "anchorXOffset": "0",
                            "anchorYOffset": "0",
                        }
                    ]
                },
            }
            if participant.get("user_id"):
                signer["clientUserId"] = str(participant["user_id"])
            signers.append(signer)
        custom_fields = [
            {"name": str(key), "value": str(value), "show": "false", "required": "false"}
            for key, value in metadata.items()
            if value is not None
        ]
        body = {
            "emailSubject": subject,
            "status": "sent",
            "documents": [
                {
                    "documentBase64": base64.b64encode(document_bytes).decode(),
                    "name": document_name,
                    "fileExtension": "pdf",
                    "documentId": "1",
                }
            ],
            "recipients": {"signers": signers},
            "customFields": {"textCustomFields": custom_fields},
        }
        payload = _json_request(
            "POST",
            f"{self.base}/v2.1/accounts/{self.settings.docusign_account_id}/envelopes",
            settings=self.settings,
            token=self.settings.docusign_access_token,
            json_body=body,
        )
        envelope_id = str(payload.get("envelopeId") or "")
        if not envelope_id:
            raise SignatureProviderRequestError("DocuSign response is missing envelopeId")
        return ProviderEnvelope(envelope_id, str(payload.get("status") or "sent"), payload)

    def create_recipient_view(
        self,
        *,
        provider_envelope_id: str,
        participant: dict[str, Any],
        return_url: str,
    ) -> ProviderRecipientView:
        if not participant.get("user_id"):
            raise SignatureProviderRequestError("Embedded DocuSign signing requires participant user_id")
        body = {
            "returnUrl": return_url,
            "authenticationMethod": "none",
            "email": participant["email"],
            "userName": participant.get("name") or participant["email"],
            "clientUserId": str(participant["user_id"]),
        }
        payload = _json_request(
            "POST",
            f"{self.base}/v2.1/accounts/{self.settings.docusign_account_id}/envelopes/{provider_envelope_id}/views/recipient",
            settings=self.settings,
            token=self.settings.docusign_access_token,
            json_body=body,
        )
        url = str(payload.get("url") or "")
        if not url:
            raise SignatureProviderRequestError("DocuSign response is missing recipient view URL")
        return ProviderRecipientView(url, payload)

    def _verify_webhook(self, raw_body: bytes, signature: str) -> None:
        expected = base64.b64encode(
            hmac.new(
                self.settings.docusign_webhook_hmac_secret.encode(),
                raw_body,
                hashlib.sha256,
            ).digest()
        ).decode()
        candidates = [item.strip() for item in signature.split(",") if item.strip()]
        if not candidates or not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
            raise InvalidSignatureWebhook("Invalid DocuSign webhook HMAC")

    def parse_webhook(
        self,
        *,
        raw_body: bytes,
        payload: dict[str, Any],
        signature: str,
    ) -> list[ProviderSignatureEvent]:
        self._verify_webhook(raw_body, signature)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        envelope_id = str(
            data.get("envelopeId")
            or ((data.get("envelopeSummary") or {}).get("envelopeId") if isinstance(data.get("envelopeSummary"), dict) else "")
            or ""
        )
        if not envelope_id:
            raise InvalidSignatureWebhook("DocuSign webhook is missing envelope id")
        event_name = str(payload.get("event") or data.get("status") or "unknown")
        recipients = data.get("recipients") or ((data.get("envelopeSummary") or {}).get("recipients") if isinstance(data.get("envelopeSummary"), dict) else {}) or {}
        signers = recipients.get("signers") if isinstance(recipients, dict) else []
        events: list[ProviderSignatureEvent] = []
        if isinstance(signers, list):
            for signer in signers:
                if not isinstance(signer, dict):
                    continue
                status = str(signer.get("status") or "").lower()
                if status not in {"completed", "signed", "declined", "delivered"}:
                    continue
                recipient_id = str(signer.get("recipientId") or "") or None
                email = str(signer.get("email") or "").lower() or None
                event_id = hashlib.sha256(
                    json.dumps(
                        [envelope_id, recipient_id, email, status, signer.get("signedDateTime")],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                events.append(
                    ProviderSignatureEvent(
                        event_id=f"docusign:{event_id}",
                        envelope_id=envelope_id,
                        email=email,
                        recipient_id=recipient_id,
                        status="signed" if status in {"completed", "signed"} else status,
                        payload={"event": event_name, "signer": signer},
                    )
                )
        if not events:
            event_id = hashlib.sha256(raw_body).hexdigest()
            events.append(
                ProviderSignatureEvent(
                    event_id=f"docusign:{event_id}",
                    envelope_id=envelope_id,
                    email=None,
                    recipient_id=None,
                    status=str(data.get("status") or event_name).lower(),
                    payload=payload,
                )
            )
        return events


def get_signature_provider(name: str | None = None, settings: Settings | None = None) -> SignatureProvider:
    settings = settings or get_settings()
    normalized = (name or settings.signature_provider).strip().lower()
    if normalized in {"external", "docusign"}:
        return DocuSignProvider(settings)
    if normalized == "local":
        return LocalSignatureProvider(settings)
    raise SignatureProviderConfigurationError(f"Unsupported signature provider: {normalized}")
