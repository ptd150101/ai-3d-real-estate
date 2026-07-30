from __future__ import annotations

import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user_optional
from ..models import User
from ..schemas import ChatRequest, ChatResponse
from ..services.chatbot import respond

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    return await respond(db, payload, user.id if user else None)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    result = await respond(db, payload, user.id if user else None)

    async def generate():
        words = result.message.split(" ")
        for word in words:
            yield f"data: {json.dumps({'type': 'delta', 'content': word + ' '}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'result', 'data': result.model_dump(mode='json')}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
