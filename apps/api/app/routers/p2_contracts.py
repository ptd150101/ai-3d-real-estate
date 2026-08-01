from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_roles
from ..models import ContractEnvelope, ContractParticipant, ContractTemplate, LegalDocumentPolicy, SignatureEvidence, User
from ..p2_dependencies import get_org_context
from ..p2_schemas import ContractEnvelopeCreate, ContractSignCreate, ContractTemplateCreate, LegalPolicyCreate
from ..services.p2_contracts import create_envelope, record_signature
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router=APIRouter(prefix="/contracts",tags=["p2-contracts"])

@router.post("/policies",dependencies=[Depends(require_roles("admin"))])
def policy(payload:LegalPolicyCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    item=db.scalar(select(LegalDocumentPolicy).where(LegalDocumentPolicy.document_type==payload.document_type,LegalDocumentPolicy.jurisdiction==payload.jurisdiction))
    if not item: item=LegalDocumentPolicy(document_type=payload.document_type,jurisdiction=payload.jurisdiction); db.add(item)
    item.approved=payload.approved; item.notes=payload.notes; item.approved_by_user_id=user.id if payload.approved else None; item.approved_at=datetime.now(timezone.utc) if payload.approved else None; db.commit(); return {"id":item.id,"approved":item.approved}

@router.post("/templates",status_code=201)
def template(payload:ContractTemplateCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_feature(db,ctx.organization.id,"contracts"); require_org_permission(ctx,"contracts.write")
    item=ContractTemplate(organization_id=ctx.organization.id,name=payload.name,document_type=payload.document_type,version=payload.version,content_html=payload.content_html,allowed_fields_json=payload.allowed_fields,active=True); db.add(item); db.commit(); return {"id":item.id,"name":item.name,"document_type":item.document_type,"version":item.version}

@router.get("/templates")
def templates(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    return [{"id":x.id,"name":x.name,"document_type":x.document_type,"version":x.version,"active":x.active} for x in db.scalars(select(ContractTemplate).where(ContractTemplate.organization_id==ctx.organization.id))]

@router.post("/envelopes",status_code=201)
def envelope(payload:ContractEnvelopeCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"contracts.write"); template=db.get(ContractTemplate,payload.template_id)
    if not template or template.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Template not found")
    item=create_envelope(db,organization_id=ctx.organization.id,template=template,reservation_order_id=payload.reservation_order_id,data=payload.data,participants=payload.participants,provider=payload.provider)
    participant_rows=[{"id":x.id,"email":x.email,"role":x.role,"status":x.status,"signing_order":x.signing_order} for x in db.scalars(select(ContractParticipant).where(ContractParticipant.envelope_id==item.id).order_by(ContractParticipant.signing_order))]
    return {"id":item.id,"status":item.status,"document_url":item.document_url,"checksum":item.document_checksum,"expires_at":item.expires_at,"participants":participant_rows}

@router.get("/envelopes")
def envelopes(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    return [{"id":x.id,"template_id":x.template_id,"status":x.status,"provider":x.provider,"document_url":x.document_url,"checksum":x.document_checksum,"expires_at":x.expires_at} for x in db.scalars(select(ContractEnvelope).where(ContractEnvelope.organization_id==ctx.organization.id).order_by(ContractEnvelope.created_at.desc()))]

@router.post("/envelopes/{envelope_id}/sign")
def sign(envelope_id:str,payload:ContractSignCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    if not payload.consent: raise HTTPException(status_code=422,detail="Explicit signing consent required")
    envelope=db.get(ContractEnvelope,envelope_id); participant=db.get(ContractParticipant,payload.participant_id)
    if not envelope or not participant or participant.envelope_id!=envelope.id: raise HTTPException(status_code=404,detail="Envelope or participant not found")
    if participant.user_id and participant.user_id!=user.id and user.role!="admin": raise HTTPException(status_code=403,detail="Signer mismatch")
    item=record_signature(db,envelope=envelope,participant=participant,provider_event_id=payload.provider_event_id,metadata={**payload.metadata,"user_id":user.id,"consent":True}); return {"id":item.id,"status":item.status,"completed_at":item.completed_at}

@router.get("/envelopes/{envelope_id}/evidence")
def evidence(envelope_id:str,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    envelope=db.get(ContractEnvelope,envelope_id)
    if not envelope or envelope.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Envelope not found")
    item=db.scalar(select(SignatureEvidence).where(SignatureEvidence.envelope_id==envelope.id))
    if not item: raise HTTPException(status_code=409,detail="Envelope is not complete")
    return {"checksum":item.checksum,"object_url":item.object_url,"evidence":item.evidence_json}
