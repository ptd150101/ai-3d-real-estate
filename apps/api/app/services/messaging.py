from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Agent,
    ConversationParticipant,
    ConversationThread,
    DirectMessage,
    MessageAttachment,
    MessageReceipt,
    Property,
    User,
)
from .notification import emit_event
from ..config import get_settings


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._redis = None
        self._pubsub = None
        self._listener: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            import redis.asyncio as redis
            self._redis = redis.from_url(get_settings().redis_url, decode_responses=True)
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe("nestora:messages")
            self._listener = asyncio.create_task(self._listen())
        except Exception:
            self._redis = None
            self._pubsub = None

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
            try: await self._listener
            except BaseException: pass
        if self._pubsub: await self._pubsub.close()
        if self._redis: await self._redis.close()

    async def _listen(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message.get("type") != "message": continue
            try:
                payload = json.loads(message["data"])
                await self._broadcast_local(payload["thread_id"], payload["payload"])
            except Exception:
                continue

    async def connect(self, thread_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock: self.connections[thread_id].add(websocket)

    async def disconnect(self, thread_id: str, websocket: WebSocket) -> None:
        async with self._lock: self.connections[thread_id].discard(websocket)

    async def _broadcast_local(self, thread_id: str, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self.connections.get(thread_id, set())):
            try: await websocket.send_json(payload)
            except Exception: stale.append(websocket)
        for websocket in stale: await self.disconnect(thread_id, websocket)

    async def publish(self, thread_id: str, payload: dict[str, Any]) -> None:
        if self._redis:
            try:
                await self._redis.publish("nestora:messages", json.dumps({"thread_id": thread_id, "payload": payload}, default=str))
                return
            except Exception:
                self._redis = None
        await self._broadcast_local(thread_id, payload)


manager = ConnectionManager()


def participant(db: Session, thread_id: str, user_id: str) -> ConversationParticipant | None:
    return db.scalar(select(ConversationParticipant).where(
        ConversationParticipant.thread_id == thread_id,
        ConversationParticipant.user_id == user_id,
    ))


def require_participant(db: Session, thread_id: str, user: User) -> ConversationParticipant:
    item = participant(db, thread_id, user.id)
    if not item and user.role == "admin":
        item = ConversationParticipant(thread_id=thread_id, user_id=user.id, role="admin")
        db.add(item)
        db.flush()
    if not item or item.blocked:
        raise PermissionError("You are not a participant in this conversation")
    return item


def create_thread(db: Session, user: User, payload) -> ConversationThread:
    assigned_agent_id = payload.agent_id
    if not assigned_agent_id and payload.property_id:
        property_obj = db.get(Property, payload.property_id)
        assigned_agent_id = property_obj.agent_id if property_obj else None
    existing = None
    if assigned_agent_id:
        existing = db.scalar(
            select(ConversationThread)
            .join(ConversationParticipant, ConversationParticipant.thread_id == ConversationThread.id)
            .where(
                ConversationThread.property_id == payload.property_id,
                ConversationThread.assigned_agent_id == assigned_agent_id,
                ConversationParticipant.user_id == user.id,
                ConversationThread.status == "open",
            )
        )
    if existing:
        return existing
    thread = ConversationThread(
        property_id=payload.property_id,
        created_by_user_id=user.id,
        assigned_agent_id=assigned_agent_id,
        subject=payload.subject,
        ai_session_id=payload.ai_session_id if payload.share_ai_transcript else None,
        ai_transcript_shared=payload.share_ai_transcript,
    )
    db.add(thread)
    db.flush()
    db.add(ConversationParticipant(thread_id=thread.id, user_id=user.id, role="buyer" if user.role == "buyer" else user.role))
    if assigned_agent_id:
        agent = db.get(Agent, assigned_agent_id)
        if agent and agent.user_id:
            db.add(ConversationParticipant(thread_id=thread.id, user_id=agent.user_id, role="agent"))
    db.flush()
    return thread


def create_message(db: Session, thread: ConversationThread, user: User, payload) -> DirectMessage:
    membership = require_participant(db, thread.id, user)
    existing = db.scalar(select(DirectMessage).where(
        DirectMessage.thread_id == thread.id,
        DirectMessage.client_message_id == payload.client_message_id,
    ))
    if existing:
        return existing
    item = DirectMessage(
        thread_id=thread.id,
        sender_user_id=user.id,
        client_message_id=payload.client_message_id,
        content=payload.content,
    )
    db.add(item)
    db.flush()
    for attachment in payload.attachments:
        db.add(MessageAttachment(
            message_id=item.id,
            file_url=str(attachment["file_url"]),
            storage_key=attachment.get("storage_key"),
            filename=str(attachment.get("filename") or "attachment"),
            content_type=str(attachment.get("content_type") or "application/octet-stream"),
            size_bytes=int(attachment.get("size_bytes") or 0),
        ))
    recipients = list(db.scalars(select(ConversationParticipant).where(
        ConversationParticipant.thread_id == thread.id,
        ConversationParticipant.user_id != user.id,
        ConversationParticipant.muted.is_(False),
        ConversationParticipant.blocked.is_(False),
    )))
    for recipient in recipients:
        db.add(MessageReceipt(message_id=item.id, user_id=recipient.user_id, delivered_at=datetime.now(timezone.utc)))
    thread.last_message_at = item.created_at
    membership.last_read_at = item.created_at
    if recipients:
        emit_event(
            db,
            event_type="chat.message_received",
            aggregate_type="conversation",
            aggregate_id=thread.id,
            recipients=[x.user_id for x in recipients],
            payload={"sender_name": user.full_name, "preview": item.content[:160], "thread_id": thread.id},
            idempotency_key=f"message:{item.id}",
            actor_user_id=user.id,
        )
    return item


def serialize_message(db: Session, item: DirectMessage) -> dict[str, Any]:
    attachments = list(db.scalars(select(MessageAttachment).where(MessageAttachment.message_id == item.id)))
    return {
        "id": item.id,
        "thread_id": item.thread_id,
        "sender_user_id": item.sender_user_id,
        "client_message_id": item.client_message_id,
        "content": item.content,
        "metadata_json": item.metadata_json,
        "created_at": item.created_at,
        "edited_at": item.edited_at,
        "attachments": [{
            "id": x.id, "file_url": f"/api/v1/messages/attachments/{x.id}" if x.storage_key else x.file_url, "filename": x.filename,
            "content_type": x.content_type, "size_bytes": x.size_bytes,
        } for x in attachments],
    }


def serialize_thread(db: Session, thread: ConversationThread, user_id: str) -> dict[str, Any]:
    participants = list(db.scalars(select(ConversationParticipant).where(ConversationParticipant.thread_id == thread.id)))
    last = db.scalar(select(DirectMessage).where(DirectMessage.thread_id == thread.id).order_by(DirectMessage.created_at.desc()).limit(1))
    me = next((x for x in participants if x.user_id == user_id), None)
    unread_stmt = select(func.count(DirectMessage.id)).where(DirectMessage.thread_id == thread.id, DirectMessage.sender_user_id != user_id)
    if me and me.last_read_at:
        unread_stmt = unread_stmt.where(DirectMessage.created_at > me.last_read_at)
    unread = int(db.scalar(unread_stmt) or 0)
    return {
        "id": thread.id,
        "property_id": thread.property_id,
        "created_by_user_id": thread.created_by_user_id,
        "assigned_agent_id": thread.assigned_agent_id,
        "subject": thread.subject,
        "status": thread.status,
        "last_message_at": thread.last_message_at,
        "unread_count": unread,
        "participants": [{"user_id": x.user_id, "role": x.role, "last_read_at": x.last_read_at} for x in participants],
        "last_message": serialize_message(db, last) if last else None,
    }
