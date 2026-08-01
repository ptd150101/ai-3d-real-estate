from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import Organization, OrganizationMember, Property, User
from ..p2_schemas import MobileDeviceCreate, MobileLoginCreate, MobileLogoutCreate, MobileMutationCreate, MobileRefreshCreate
from ..services.p2_mobile import apply_mutation, mobile_login, register_device, revoke_mobile_tokens, rotate_refresh_token

router=APIRouter(prefix="/mobile",tags=["p2-mobile"])

@router.post("/auth/login")
def login(payload:MobileLoginCreate,db:Session=Depends(get_db)): return mobile_login(db,str(payload.email),payload.password,payload.device_id)

@router.post("/auth/refresh")
def refresh(payload:MobileRefreshCreate,db:Session=Depends(get_db)): return rotate_refresh_token(db,payload.refresh_token,payload.device_id)

@router.post("/auth/logout")
def logout(payload: MobileLogoutCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"revoked": revoke_mobile_tokens(db, user, payload.device_id, payload.refresh_token)}

@router.post("/devices",status_code=201)
def device(payload:MobileDeviceCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    item=register_device(db,user,payload.device_id,payload.platform,payload.push_token,payload.app_version); return {"id":item.id,"device_id":item.device_id,"platform":item.platform,"push_registered":bool(item.push_token)}

@router.post("/mutations",status_code=201)
def mutation(payload:MobileMutationCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    item=apply_mutation(db,user,payload.device_id,payload.client_mutation_id,payload.mutation_type,payload.payload); return {"id":item.id,"status":item.status,"result":item.result_json}

@router.get("/bootstrap")
def bootstrap(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    orgs=[]
    for m in db.scalars(select(OrganizationMember).where(OrganizationMember.user_id==user.id,OrganizationMember.status=="active")):
        org=db.get(Organization,m.organization_id)
        if org: orgs.append({"id":org.id,"name":org.name,"slug":org.slug,"role":m.role})
    properties=[{"id":x.id,"slug":x.slug,"title":x.title,"price":x.price,"district":x.district,"has_3d":x.has_3d} for x in db.scalars(select(Property).where(Property.status=="published").limit(50))]
    return {"user":{"id":user.id,"full_name":user.full_name,"role":user.role},"organizations":orgs,"properties":properties,"deep_links":["nestora://property/{slug}","nestora://messages/{thread_id}","nestora://capture/{session_id}"]}
