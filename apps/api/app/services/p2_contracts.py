from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ContractEnvelope, ContractParticipant, ContractTemplate, LegalDocumentPolicy, SignatureEvent, SignatureEvidence


def _render_pdf(title: str, body: str) -> bytes:
    buffer=io.BytesIO(); font="Helvetica"
    for candidate in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path(candidate).exists():
            try: pdfmetrics.registerFont(TTFont("NestoraUnicode",candidate)); font="NestoraUnicode"; break
            except Exception: pass
    c=canvas.Canvas(buffer,pagesize=A4); width,height=A4; c.setFont(font,16); c.drawString(48,height-60,title); c.setFont(font,10)
    y=height-90
    for paragraph in body.replace("<br>","\n").replace("<p>","").replace("</p>","\n").splitlines():
        words=paragraph.split(); line=""
        for word in words:
            if c.stringWidth(line+" "+word,font,10)>width-96: c.drawString(48,y,line); y-=15; line=word
            else: line=(line+" "+word).strip()
        if line: c.drawString(48,y,line); y-=15
        if y<60: c.showPage(); c.setFont(font,10); y=height-60
    c.save(); return buffer.getvalue()


def create_envelope(db: Session, *, organization_id: str, template: ContractTemplate, reservation_order_id: str | None, data: dict, participants: list[dict], provider: str="local") -> ContractEnvelope:
    policy=db.scalar(select(LegalDocumentPolicy).where(LegalDocumentPolicy.document_type==template.document_type,LegalDocumentPolicy.jurisdiction=="VN"))
    if not policy or not policy.approved: raise HTTPException(status_code=409,detail="Document type has not passed legal approval")
    content=template.content_html
    for field in template.allowed_fields_json:
        content=content.replace("{{"+field+"}}",str(data.get(field,"")))
    pdf=_render_pdf(template.name,content); checksum=hashlib.sha256(pdf).hexdigest()
    envelope=ContractEnvelope(organization_id=organization_id,template_id=template.id,reservation_order_id=reservation_order_id,status="sent",provider=provider,document_checksum=checksum,data_json=data,expires_at=datetime.now(timezone.utc)+timedelta(days=7))
    db.add(envelope); db.flush()
    root=get_settings().storage_path/"private"/"contracts"; root.mkdir(parents=True,exist_ok=True); path=root/f"{envelope.id}.pdf"; path.write_bytes(pdf); envelope.document_url=f"/storage/private/contracts/{envelope.id}.pdf"
    for index,p in enumerate(participants,1): db.add(ContractParticipant(envelope_id=envelope.id,user_id=p.get("user_id"),email=p["email"],role=p.get("role","signer"),signing_order=p.get("signing_order",index),status="pending"))
    db.commit(); db.refresh(envelope); return envelope


def record_signature(db: Session, *, envelope: ContractEnvelope, participant: ContractParticipant, provider_event_id: str, metadata: dict) -> ContractEnvelope:
    if db.scalar(select(SignatureEvent).where(SignatureEvent.provider_event_id==provider_event_id)): return envelope
    if envelope.status in {"completed","voided","expired"}: return envelope
    participant.status="signed"; participant.signed_at=datetime.now(timezone.utc)
    db.add(SignatureEvent(envelope_id=envelope.id,participant_id=participant.id,event_type="signed",provider_event_id=provider_event_id,event_at=participant.signed_at,metadata_json=metadata)); db.flush()
    pending=db.scalar(select(ContractParticipant).where(ContractParticipant.envelope_id==envelope.id,ContractParticipant.status!="signed").limit(1))
    if not pending:
        envelope.status="completed"; envelope.completed_at=datetime.now(timezone.utc)
        evidence={"envelope_id":envelope.id,"document_checksum":envelope.document_checksum,"completed_at":envelope.completed_at.isoformat(),"events":[{"id":e.id,"type":e.event_type,"provider_event_id":e.provider_event_id,"event_at":e.event_at.isoformat()} for e in db.scalars(select(SignatureEvent).where(SignatureEvent.envelope_id==envelope.id).order_by(SignatureEvent.event_at))]}
        checksum=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        db.add(SignatureEvidence(envelope_id=envelope.id,checksum=checksum,evidence_json=evidence,object_url=envelope.document_url))
    db.commit(); db.refresh(envelope); return envelope


def expire_and_remind(db: Session) -> dict:
    now=datetime.now(timezone.utc); expired=0; reminders=0
    for envelope in db.scalars(select(ContractEnvelope).where(ContractEnvelope.status=="sent")):
        exp=envelope.expires_at
        if exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc))<=now: envelope.status="expired"; expired+=1
        elif exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc))-now<timedelta(hours=24): reminders+=1
    db.commit(); return {"expired":expired,"reminders":reminders}
