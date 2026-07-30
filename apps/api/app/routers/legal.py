from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import client_ip, get_current_user, get_current_user_optional, require_roles
from ..models import LegalDocumentVersion, PropertyDocument, User
from ..p1_schemas import LegalGrantCreate, LegalReviewCreate, LegalVersionCreate, LegalVersionRead
from ..services.legal import create_grant, create_version, record_download, review_version, validate_grant, watermark_pdf
from ..services.storage import read_limited, read_private_bytes, save_private_bytes, validate_upload

router = APIRouter(tags=["legal"])


@router.get("/properties/{property_id}/legal-documents")
def public_documents(property_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(PropertyDocument, LegalDocumentVersion)
        .join(LegalDocumentVersion, LegalDocumentVersion.property_document_id == PropertyDocument.id)
        .where(PropertyDocument.property_id == property_id, LegalDocumentVersion.status == "approved", LegalDocumentVersion.active.is_(True))
        .order_by(PropertyDocument.created_at.desc())
    ).all()
    return [{"document_id": doc.id, "title": doc.title, "document_type": doc.document_type, "verified": doc.verified, "version": version.version_number, "valid_until": version.valid_until} for doc, version in rows]


@router.post("/admin/legal/documents/{document_id}/upload", response_model=LegalVersionRead, status_code=201)
def upload_private_document(document_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "agent", "legal_reviewer"))):
    import hashlib
    document = db.get(PropertyDocument, document_id)
    if not document: raise HTTPException(status_code=404, detail="Property document not found")
    data = read_limited(file.file); content_type = validate_upload(file.filename or "document.pdf", file.content_type, len(data))
    if content_type != "application/pdf": raise HTTPException(status_code=400, detail="Legal documents must be PDF")
    storage_key, size, _ = save_private_bytes(data, file.filename or "document.pdf", f"legal/{document.property_id}", content_type)
    payload = LegalVersionCreate(property_document_id=document.id, storage_key=storage_key, checksum_sha256=hashlib.sha256(data).hexdigest(), content_type=content_type, size_bytes=size)
    item = create_version(db, user, payload); db.commit(); db.refresh(item); return item


@router.get("/admin/legal/versions", response_model=list[LegalVersionRead])
def versions(status: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "legal_reviewer"))):
    stmt = select(LegalDocumentVersion)
    if status: stmt = stmt.where(LegalDocumentVersion.status == status)
    return list(db.scalars(stmt.order_by(LegalDocumentVersion.created_at.desc())))


@router.post("/admin/legal/versions", response_model=LegalVersionRead, status_code=201)
def upload_version(payload: LegalVersionCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "agent", "legal_reviewer"))):
    try:
        item = create_version(db, user, payload); db.commit(); db.refresh(item); return item
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/legal/versions/{version_id}/review", response_model=LegalVersionRead)
def review(version_id: str, payload: LegalReviewCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "legal_reviewer"))):
    item = db.get(LegalDocumentVersion, version_id)
    if not item: raise HTTPException(status_code=404, detail="Version not found")
    try:
        review_version(db, item, user, payload.decision, payload.notes); db.commit(); db.refresh(item); return item
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/admin/legal/grants", status_code=201)
def grant_access(payload: LegalGrantCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "agent", "legal_reviewer"))):
    try:
        item, raw_token = create_grant(db, user, payload); db.commit()
        return {"id": item.id, "token": raw_token, "download_url": f"/api/v1/legal/download?token={raw_token}", "expires_at": item.expires_at}
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/legal/download")
def download(request: Request, token: str = Query(...), db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    try:
        grant, version = validate_grant(db, token, user.id if user else None)
        data = read_private_bytes(version.storage_key)
        label = f"Nestora access {grant.id} · user {user.id if user else 'guest'} · {__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}"
        output, watermarked = watermark_pdf(data, label)
        record_download(db, grant, user.id if user else None, client_ip(request), request.headers.get("user-agent"), watermarked=watermarked)
        db.commit()
        return StreamingResponse(iter([output]), media_type=version.content_type, headers={"Content-Disposition": f'attachment; filename="legal-v{version.version_number}.pdf"', "Cache-Control": "private, no-store"})
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, OSError) as exc: raise HTTPException(status_code=410, detail=str(exc)) from exc

