from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..dependencies import get_current_user
from ..models import ConversationParticipant, ConversationThread, DirectMessage, MessageAttachment, MessageReceipt, User
from ..p1_schemas import MessageCreate, ThreadCreate
from ..security import create_access_token, decode_access_token
from ..services.messaging import create_message, create_thread, manager, require_participant, serialize_message, serialize_thread
from ..services.storage import read_limited, read_private_bytes, save_private_bytes, validate_upload
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["messaging"])


@router.post("/messages/attachments/upload", status_code=201)
def upload_attachment(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    data = read_limited(file.file); content_type = validate_upload(file.filename or "attachment.bin", file.content_type, len(data))
    storage_key, size, _ = save_private_bytes(data, file.filename or "attachment.bin", f"messages/{user.id}", content_type)
    return {"storage_key": storage_key, "file_url": "private", "filename": file.filename or "attachment.bin", "content_type": content_type, "size_bytes": size}


@router.get("/messages/attachments/{attachment_id}")
def download_attachment(attachment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(MessageAttachment, attachment_id)
    if not item: raise HTTPException(status_code=404, detail="Attachment not found")
    message = db.get(DirectMessage, item.message_id)
    if not message: raise HTTPException(status_code=404, detail="Message not found")
    try: require_participant(db, message.thread_id, user)
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not item.storage_key: raise HTTPException(status_code=410, detail="Attachment storage missing")
    data = read_private_bytes(item.storage_key)
    return StreamingResponse(iter([data]), media_type=item.content_type, headers={"Content-Disposition": f'attachment; filename="{item.filename}"', "Cache-Control": "private, no-store"})


@router.get("/messages/threads")
def threads(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = list(db.scalars(
        select(ConversationThread)
        .join(ConversationParticipant, ConversationParticipant.thread_id == ConversationThread.id)
        .where(ConversationParticipant.user_id == user.id)
        .order_by(ConversationThread.last_message_at.desc().nullslast(), ConversationThread.created_at.desc())
    ))
    return [serialize_thread(db, x, user.id) for x in rows]


@router.post("/messages/threads", status_code=201)
def new_thread(payload: ThreadCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = create_thread(db, user, payload); db.commit(); db.refresh(item); return serialize_thread(db, item, user.id)


@router.get("/messages/threads/{thread_id}")
def get_thread(thread_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(ConversationThread, thread_id)
    if not item: raise HTTPException(status_code=404, detail="Thread not found")
    try: require_participant(db, thread_id, user)
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    return serialize_thread(db, item, user.id)


@router.get("/messages/threads/{thread_id}/messages")
def list_messages(thread_id: str, before: str | None = None, limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try: participant = require_participant(db, thread_id, user)
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    stmt = select(DirectMessage).where(DirectMessage.thread_id == thread_id, DirectMessage.deleted_at.is_(None)).order_by(DirectMessage.created_at.desc()).limit(limit)
    if before:
        pivot = db.get(DirectMessage, before)
        if pivot: stmt = stmt.where(DirectMessage.created_at < pivot.created_at)
    rows = list(reversed(list(db.scalars(stmt))))
    if rows:
        participant.last_read_at = rows[-1].created_at
        db.query(MessageReceipt).filter(MessageReceipt.message_id.in_([x.id for x in rows]), MessageReceipt.user_id == user.id, MessageReceipt.read_at.is_(None)).update({"read_at": rows[-1].created_at}, synchronize_session=False)
        db.commit()
    return [serialize_message(db, x) for x in rows]


@router.post("/messages/threads/{thread_id}/messages", status_code=201)
async def send_message(thread_id: str, payload: MessageCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    thread = db.get(ConversationThread, thread_id)
    if not thread: raise HTTPException(status_code=404, detail="Thread not found")
    try:
        item = create_message(db, thread, user, payload); db.commit(); db.refresh(item)
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    result = serialize_message(db, item)
    await manager.publish(thread_id, {"type": "message", "message": result})
    return result


@router.post("/messages/threads/{thread_id}/read", status_code=204)
def mark_thread_read(thread_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try: item = require_participant(db, thread_id, user)
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    from datetime import datetime, timezone
    item.last_read_at = datetime.now(timezone.utc); db.commit(); return None




@router.post("/messages/socket-token")
def socket_token(user: User = Depends(get_current_user)):
    return {"token": create_access_token(user.id, user.role, expires_minutes=5)}


@router.websocket("/messages/ws/{thread_id}")
async def message_socket(websocket: WebSocket, thread_id: str, token: str = Query(...)):
    db = SessionLocal()
    try:
        try:
            payload = decode_access_token(token)
            user = db.get(User, payload.get("sub"))
            if not user: raise ValueError("user missing")
            require_participant(db, thread_id, user)
        except Exception:
            await websocket.close(code=4401)
            return
        await manager.connect(thread_id, websocket)
        await websocket.send_json({"type": "connected", "thread_id": thread_id})
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "typing":
                await manager.publish(thread_id, {"type": "typing", "user_id": user.id, "active": bool(data.get("active"))})
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(thread_id, websocket)
        db.close()
