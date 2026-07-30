from typing import Any
from sqlalchemy.orm import Session
from ..models import AuditLog, User

def write_audit(db: Session, *, actor: User | None, action: str, entity_type: str, entity_id: str | None, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None, ip_address: str | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id if actor else None, action=action, entity_type=entity_type, entity_id=entity_id, before_json=before, after_json=after, ip_address=ip_address))
