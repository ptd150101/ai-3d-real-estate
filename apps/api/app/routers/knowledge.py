from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_roles
from ..models import KnowledgeDocument, User
from ..schemas import KnowledgeDocumentCreate, KnowledgeDocumentRead
from ..services.rag import index_document, retrieve

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

@router.get("", response_model=list[KnowledgeDocumentRead])
def list_documents(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    return list(db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())))

@router.post("", response_model=KnowledgeDocumentRead, status_code=201)
def create_document(payload: KnowledgeDocumentCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = KnowledgeDocument(**payload.model_dump()); db.add(item); db.flush(); index_document(db, item); db.commit(); db.refresh(item); return item

@router.put("/{document_id}", response_model=KnowledgeDocumentRead)
def update_document(document_id: str, payload: KnowledgeDocumentCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = db.get(KnowledgeDocument, document_id)
    if not item: raise HTTPException(status_code=404, detail="Document not found")
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    index_document(db, item); db.commit(); db.refresh(item); return item

@router.get("/search")
def search_knowledge(q: str, property_id: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    return retrieve(db, q, property_id=property_id, verified_only=False, limit=10)
