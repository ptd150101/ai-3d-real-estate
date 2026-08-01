from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from .database import get_db
from .dependencies import get_current_user
from .models import User
from .services.p2_tenant import OrgContext, resolve_org_context


def get_org_context(
    x_organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrgContext:
    return resolve_org_context(db,user,x_organization_id)
