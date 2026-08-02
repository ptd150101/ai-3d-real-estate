from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from ..config import get_settings


class PushDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class PushMessage:
    to: str
    title: str
    body: str
    data: dict[str, Any]
    sound: str = "default"
    channel_id: str = "general"


def _chunks(items: list[PushMessage], size: int = 100) -> Iterable[list[PushMessage]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def is_expo_push_token(token: str) -> bool:
    return token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken[")


def send_expo_push(messages: list[PushMessage]) -> list[dict[str, Any]]:
    if not messages:
        return []
    invalid = [message.to for message in messages if not is_expo_push_token(message.to)]
    if invalid:
        raise PushDeliveryError(f"Invalid Expo push token(s): {len(invalid)}")
    settings = get_settings()
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "accept-encoding": "gzip, deflate",
    }
    if settings.expo_access_token:
        headers["authorization"] = f"Bearer {settings.expo_access_token}"
    tickets: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=settings.provider_http_timeout_seconds) as client:
            for batch in _chunks(messages):
                response = client.post(
                    settings.expo_push_url,
                    headers=headers,
                    json=[
                        {
                            "to": message.to,
                            "title": message.title,
                            "body": message.body,
                            "data": message.data,
                            "sound": message.sound,
                            "channelId": message.channel_id,
                        }
                        for message in batch
                    ],
                )
                response.raise_for_status()
                payload = response.json()
                batch_tickets = payload.get("data", payload)
                if isinstance(batch_tickets, dict):
                    batch_tickets = [batch_tickets]
                if not isinstance(batch_tickets, list):
                    raise PushDeliveryError("Expo returned an invalid ticket response")
                tickets.extend(item for item in batch_tickets if isinstance(item, dict))
    except PushDeliveryError:
        raise
    except Exception as exc:
        raise PushDeliveryError(f"Expo push delivery failed: {exc}") from exc
    return tickets


def fetch_expo_receipts(ticket_ids: list[str]) -> dict[str, Any]:
    if not ticket_ids:
        return {}
    settings = get_settings()
    receipt_url = settings.expo_push_url.rsplit("/", 1)[0] + "/getReceipts"
    headers = {"content-type": "application/json", "accept": "application/json"}
    if settings.expo_access_token:
        headers["authorization"] = f"Bearer {settings.expo_access_token}"
    try:
        with httpx.Client(timeout=settings.provider_http_timeout_seconds) as client:
            response = client.post(receipt_url, headers=headers, json={"ids": ticket_ids[:1000]})
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        raise PushDeliveryError(f"Expo receipt lookup failed: {exc}") from exc
