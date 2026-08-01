from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Favorite, MobileDevice, MobileMutation, MobileRefreshToken, Property, User
from ..security import create_access_token, verify_password


def _hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(db: Session, user: User, device_id: str) -> tuple[str,MobileRefreshToken]:
    raw=secrets.token_urlsafe(48); item=MobileRefreshToken(user_id=user.id,device_id=device_id,token_hash=_hash(raw),expires_at=datetime.now(timezone.utc)+timedelta(days=30)); db.add(item); db.commit(); db.refresh(item); return raw,item


def mobile_login(db: Session, email: str, password: str, device_id: str) -> dict:
    user=db.scalar(select(User).where(User.email==email.lower()))
    if not user or not verify_password(password,user.password_hash): raise HTTPException(status_code=401,detail="Invalid credentials")
    raw,_=issue_refresh_token(db,user,device_id); return {"access_token":create_access_token(user.id,user.role,60),"refresh_token":raw,"token_type":"bearer","expires_in":3600,"user":{"id":user.id,"email":user.email,"full_name":user.full_name,"role":user.role}}


def rotate_refresh_token(db: Session, raw: str, device_id: str) -> dict:
    item=db.scalar(select(MobileRefreshToken).where(MobileRefreshToken.token_hash==_hash(raw),MobileRefreshToken.device_id==device_id))
    if not item or item.revoked_at: raise HTTPException(status_code=401,detail="Refresh token invalid")
    expires=item.expires_at if item.expires_at.tzinfo else item.expires_at.replace(tzinfo=timezone.utc)
    if expires<=datetime.now(timezone.utc): raise HTTPException(status_code=401,detail="Refresh token expired")
    user=db.get(User,item.user_id); new_raw,new_item=issue_refresh_token(db,user,device_id); item.revoked_at=datetime.now(timezone.utc); item.replaced_by_id=new_item.id; db.commit()
    return {"access_token":create_access_token(user.id,user.role,60),"refresh_token":new_raw,"token_type":"bearer","expires_in":3600}


def register_device(db: Session, user: User, device_id: str, platform: str, push_token: str | None, app_version: str | None) -> MobileDevice:
    item=db.scalar(select(MobileDevice).where(MobileDevice.user_id==user.id,MobileDevice.device_id==device_id))
    if not item: item=MobileDevice(user_id=user.id,device_id=device_id,platform=platform,push_token=push_token,app_version=app_version); db.add(item)
    else: item.platform=platform; item.push_token=push_token; item.app_version=app_version; item.last_seen_at=datetime.now(timezone.utc)
    db.commit(); db.refresh(item); return item


def apply_mutation(db: Session, user: User, device_id: str, client_mutation_id: str, mutation_type: str, payload: dict) -> MobileMutation:
    existing=db.scalar(select(MobileMutation).where(MobileMutation.user_id==user.id,MobileMutation.device_id==device_id,MobileMutation.client_mutation_id==client_mutation_id))
    if existing: return existing
    result={"applied":True}
    if mutation_type=="favorite.add":
        property_id=payload.get("property_id");
        if not db.get(Property,property_id): raise HTTPException(status_code=404,detail="Property not found")
        if not db.scalar(select(Favorite).where(Favorite.user_id==user.id,Favorite.property_id==property_id)): db.add(Favorite(user_id=user.id,property_id=property_id))
        result["property_id"]=property_id
    elif mutation_type=="favorite.remove":
        item=db.scalar(select(Favorite).where(Favorite.user_id==user.id,Favorite.property_id==payload.get("property_id")))
        if item: db.delete(item)
    elif mutation_type not in {"capture.metadata","analytics.event"}: raise HTTPException(status_code=422,detail="Unsupported mutation type")
    mutation=MobileMutation(user_id=user.id,device_id=device_id,client_mutation_id=client_mutation_id,mutation_type=mutation_type,payload_json=payload,status="applied",result_json=result); db.add(mutation); db.commit(); db.refresh(mutation); return mutation


def revoke_mobile_tokens(db: Session, user: User, device_id: str, raw: str | None = None) -> int:
    stmt = select(MobileRefreshToken).where(MobileRefreshToken.user_id == user.id, MobileRefreshToken.device_id == device_id, MobileRefreshToken.revoked_at.is_(None))
    if raw:
        stmt = stmt.where(MobileRefreshToken.token_hash == _hash(raw))
    count = 0
    for item in db.scalars(stmt):
        item.revoked_at = datetime.now(timezone.utc)
        count += 1
    db.commit()
    return count
