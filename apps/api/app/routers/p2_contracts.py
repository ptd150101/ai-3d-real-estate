from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import get_current_user, require_roles
from ..models import (
    ContractEnvelope,
    ContractParticipant,
    ContractTemplate,
    LegalDocumentPolicy,
    OrganizationMember,
    SignatureEvidence,
    User,
)
from ..p2_dependencies import get_org_context
from ..p2_schemas import ContractEnvelopeCreate, ContractSignCreate, ContractTemplateCreate, LegalPolicyCreate
from ..services.p2_contracts import (
    create_envelope,
    create_provider_signing_view,
    issue_signing_token,
    process_provider_webhook,
    record_signature,
    verify_signing_token,
)
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission
from ..services.storage import StorageError, presign_private_url, read_private_bytes

router = APIRouter(prefix="/contracts", tags=["p2-contracts"])


def _document_url(envelope_id: str) -> str:
    return f"/api/v1/contracts/envelopes/{envelope_id}/document"


@router.post("/policies", dependencies=[Depends(require_roles("admin"))])
def policy(
    payload: LegalPolicyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.scalar(
        select(LegalDocumentPolicy).where(
            LegalDocumentPolicy.document_type == payload.document_type,
            LegalDocumentPolicy.jurisdiction == payload.jurisdiction,
        )
    )
    if not item:
        item = LegalDocumentPolicy(document_type=payload.document_type, jurisdiction=payload.jurisdiction)
        db.add(item)
    item.approved = payload.approved
    item.notes = payload.notes
    item.approved_by_user_id = user.id if payload.approved else None
    item.approved_at = datetime.now(timezone.utc) if payload.approved else None
    db.commit()
    return {"id": item.id, "approved": item.approved}


@router.post("/templates", status_code=201)
def template(
    payload: ContractTemplateCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_feature(db, ctx.organization.id, "contracts")
    require_org_permission(ctx, "contracts.write")
    item = ContractTemplate(
        organization_id=ctx.organization.id,
        name=payload.name,
        document_type=payload.document_type,
        version=payload.version,
        content_html=payload.content_html,
        allowed_fields_json=payload.allowed_fields,
        active=True,
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name, "document_type": item.document_type, "version": item.version}


@router.get("/templates")
def templates(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "name": item.name,
            "document_type": item.document_type,
            "version": item.version,
            "active": item.active,
        }
        for item in db.scalars(
            select(ContractTemplate).where(ContractTemplate.organization_id == ctx.organization.id)
        )
    ]


@router.post("/envelopes", status_code=201)
def envelope(
    payload: ContractEnvelopeCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_feature(db, ctx.organization.id, "contracts")
    require_org_permission(ctx, "contracts.write")
    template = db.get(ContractTemplate, payload.template_id)
    if not template or template.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Template not found")
    item = create_envelope(
        db,
        organization_id=ctx.organization.id,
        template=template,
        reservation_order_id=payload.reservation_order_id,
        data=payload.data,
        participants=payload.participants,
        provider=payload.provider,
    )
    participant_rows = [
        {
            "id": participant.id,
            "email": participant.email,
            "role": participant.role,
            "status": participant.status,
            "signing_order": participant.signing_order,
        }
        for participant in db.scalars(
            select(ContractParticipant)
            .where(ContractParticipant.envelope_id == item.id)
            .order_by(ContractParticipant.signing_order)
        )
    ]
    return {
        "id": item.id,
        "status": item.status,
        "provider": item.provider,
        "document_url": _document_url(item.id),
        "checksum": item.document_checksum,
        "expires_at": item.expires_at,
        "participants": participant_rows,
    }


@router.get("/envelopes")
def envelopes(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "template_id": item.template_id,
            "status": item.status,
            "provider": item.provider,
            "document_url": _document_url(item.id),
            "checksum": item.document_checksum,
            "expires_at": item.expires_at,
        }
        for item in db.scalars(
            select(ContractEnvelope)
            .where(ContractEnvelope.organization_id == ctx.organization.id)
            .order_by(ContractEnvelope.created_at.desc())
        )
    ]


@router.post("/envelopes/{envelope_id}/participants/{participant_id}/signing-token")
def create_participant_signing_token(
    envelope_id: str,
    participant_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "contracts.write")
    envelope = db.get(ContractEnvelope, envelope_id)
    participant = db.get(ContractParticipant, participant_id)
    if (
        not envelope
        or envelope.organization_id != ctx.organization.id
        or not participant
        or participant.envelope_id != envelope.id
    ):
        raise HTTPException(status_code=404, detail="Envelope or participant not found")
    if envelope.provider != "local":
        raise HTTPException(status_code=409, detail="External envelope uses a provider signing view")
    if participant.status == "signed":
        raise HTTPException(status_code=409, detail="Participant has already signed")
    if envelope.status != "sent":
        raise HTTPException(status_code=409, detail="Envelope is not open for signing")
    token, expires_at = issue_signing_token(envelope, participant)
    return {
        "signing_token": token,
        "expires_at": expires_at,
        "participant_id": participant.id,
        "envelope_id": envelope.id,
    }


@router.post("/envelopes/{envelope_id}/participants/{participant_id}/provider-view")
def provider_signing_view(
    envelope_id: str,
    participant_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    envelope = db.get(ContractEnvelope, envelope_id)
    participant = db.get(ContractParticipant, participant_id)
    if not envelope or not participant or participant.envelope_id != envelope.id:
        raise HTTPException(status_code=404, detail="Envelope or participant not found")
    if participant.user_id and participant.user_id != user.id:
        raise HTTPException(status_code=403, detail="Signer identity does not match participant")
    if not participant.user_id and participant.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="Signer email does not match participant")
    return {"url": create_provider_signing_view(db, envelope=envelope, participant=participant)}


@router.post("/envelopes/{envelope_id}/sign")
def sign(
    envelope_id: str,
    payload: ContractSignCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.consent:
        raise HTTPException(status_code=422, detail="Explicit signing consent required")
    envelope = db.get(ContractEnvelope, envelope_id)
    participant = db.get(ContractParticipant, payload.participant_id)
    if not envelope or not participant or participant.envelope_id != envelope.id:
        raise HTTPException(status_code=404, detail="Envelope or participant not found")
    if envelope.provider != "local":
        raise HTTPException(status_code=409, detail="External envelopes must be signed at the provider")

    if payload.signing_token:
        claims = verify_signing_token(
            payload.signing_token,
            envelope_id=envelope.id,
            participant_id=participant.id,
        )
        provider_event_id = f"local:{claims['jti']}"
    else:
        if get_settings().environment == "production":
            raise HTTPException(status_code=401, detail="Signing token is required")
        claims = {"jti": f"authenticated-{envelope.id}-{participant.id}"}
        provider_event_id = f"authenticated:{envelope.id}:{participant.id}"

    if participant.user_id:
        if participant.user_id != user.id:
            raise HTTPException(status_code=403, detail="Signer identity does not match participant")
    elif participant.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="Signer email does not match participant")

    item = record_signature(
        db,
        envelope=envelope,
        participant=participant,
        provider_event_id=provider_event_id,
        metadata={
            **payload.metadata,
            "user_id": user.id,
            "user_email": user.email.lower(),
            "consent": True,
            "token_jti": claims["jti"],
        },
    )
    return {"id": item.id, "status": item.status, "completed_at": item.completed_at}


@router.post("/webhooks/{provider}")
async def signature_webhook(
    provider: str,
    request: Request,
    x_docusign_signature_1: str = Header(default="", alias="X-DocuSign-Signature-1"),
    x_signature: str = Header(default="", alias="X-Signature"),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid signature webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Signature webhook body must be an object")
    signature = x_docusign_signature_1 or x_signature
    return process_provider_webhook(
        db,
        provider=provider.lower(),
        raw_body=raw_body,
        payload=payload,
        signature=signature,
    )


@router.get("/envelopes/{envelope_id}/document")
def download_document(
    envelope_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    envelope = db.get(ContractEnvelope, envelope_id)
    if not envelope or not envelope.document_url:
        raise HTTPException(status_code=404, detail="Document not found")
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == envelope.organization_id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
    )
    participant = db.scalar(
        select(ContractParticipant).where(
            ContractParticipant.envelope_id == envelope.id,
            (
                (ContractParticipant.user_id == user.id)
                | (
                    ContractParticipant.user_id.is_(None)
                    & (ContractParticipant.email == user.email.lower())
                )
            ),
        )
    )
    if not member and not participant and user.role != "admin":
        raise HTTPException(status_code=404, detail="Document not found")
    signed_url = presign_private_url(envelope.document_url)
    if signed_url:
        return RedirectResponse(signed_url, status_code=307, headers={"cache-control": "private, no-store"})
    try:
        content = read_private_bytes(envelope.document_url)
    except (StorageError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "content-disposition": f'attachment; filename="contract-{envelope.id}.pdf"',
            "cache-control": "private, no-store",
        },
    )


@router.get("/envelopes/{envelope_id}/evidence")
def evidence(
    envelope_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    envelope = db.get(ContractEnvelope, envelope_id)
    if not envelope or envelope.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Envelope not found")
    item = db.scalar(select(SignatureEvidence).where(SignatureEvidence.envelope_id == envelope.id))
    if not item:
        raise HTTPException(status_code=409, detail="Envelope is not complete")
    return {
        "checksum": item.checksum,
        "object_url": _document_url(envelope.id),
        "evidence": item.evidence_json,
    }
