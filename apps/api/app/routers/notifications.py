from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import NotificationDelivery, NotificationEvent, NotificationPreference, Property, SavedSearch, SavedSearchMatch, SavedSearchSubscription, User
from ..p1_schemas import (
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    NotificationWebhook,
    SavedSearchMatchRead,
    SavedSearchSubscriptionRead,
    SavedSearchSubscriptionUpdate,
)
from ..services.notification import consume_unsubscribe_token, preference_for, update_delivery_from_webhook, verify_webhook_signature
from ..services.saved_search import get_or_create_subscription, match_saved_search
from ..services.serializers import property_summary

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications(limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(
        select(NotificationDelivery, NotificationEvent.event_type)
        .join(NotificationEvent, NotificationEvent.id == NotificationDelivery.event_id)
        .where(NotificationDelivery.user_id == user.id, NotificationDelivery.channel == "in_app")
        .order_by(NotificationDelivery.created_at.desc())
        .limit(min(limit, 100))
    ).all()
    return [NotificationRead(id=item.id, event_type=event_type, channel=item.channel, subject=item.subject, body=item.body, status=item.status, read_at=item.read_at, created_at=item.created_at) for item, event_type in rows]


@router.patch("/notifications/{notification_id}/read", status_code=204)
def mark_read(notification_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(NotificationDelivery, notification_id)
    if not item or item.user_id != user.id or item.channel != "in_app":
        raise HTTPException(status_code=404, detail="Notification not found")
    from datetime import datetime, timezone
    item.read_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=204)


@router.post("/notifications/read-all", status_code=204)
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from datetime import datetime, timezone
    db.query(NotificationDelivery).filter(
        NotificationDelivery.user_id == user.id,
        NotificationDelivery.channel == "in_app",
        NotificationDelivery.read_at.is_(None),
    ).update({"read_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    return Response(status_code=204)


@router.get("/notification-preferences", response_model=NotificationPreferenceRead)
def get_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = preference_for(db, user.id)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/notification-preferences", response_model=NotificationPreferenceRead)
def update_preferences(payload: NotificationPreferenceUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = preference_for(db, user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    return item


@router.get("/notifications/unsubscribe")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    try:
        item = consume_unsubscribe_token(db, token); db.commit()
        return {"status": "unsubscribed", "channel": item.channel, "event_type": item.event_type}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/webhooks/notifications/{provider}", status_code=204)
async def notification_webhook(provider: str, payload: NotificationWebhook, request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not verify_webhook_signature(raw, request.headers.get("x-signature")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    if not update_delivery_from_webhook(db, payload.provider_message_id, payload.status, payload.error):
        raise HTTPException(status_code=404, detail="Delivery not found")
    return Response(status_code=204)


@router.get("/saved-searches/{search_id}/subscription", response_model=SavedSearchSubscriptionRead)
def get_subscription(search_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    saved = db.get(SavedSearch, search_id)
    if not saved or saved.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved search not found")
    item = get_or_create_subscription(db, saved)
    db.commit(); db.refresh(item)
    return item


@router.put("/saved-searches/{search_id}/subscription", response_model=SavedSearchSubscriptionRead)
def update_subscription(search_id: str, payload: SavedSearchSubscriptionUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    saved = db.get(SavedSearch, search_id)
    if not saved or saved.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved search not found")
    item = get_or_create_subscription(db, saved)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    saved.notify = item.is_active and item.frequency != "off"
    db.commit(); db.refresh(item)
    return item


@router.post("/saved-searches/{search_id}/run")
def run_saved_search(search_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    saved = db.get(SavedSearch, search_id)
    if not saved or saved.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return match_saved_search(db, search_id, notify=False)


@router.get("/saved-searches/{search_id}/matches", response_model=list[SavedSearchMatchRead])
def saved_search_matches(search_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    saved = db.get(SavedSearch, search_id)
    if not saved or saved.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved search not found")
    matches = list(db.scalars(select(SavedSearchMatch).where(SavedSearchMatch.saved_search_id == search_id).order_by(SavedSearchMatch.matched_at.desc())))
    output = []
    for item in matches:
        prop = db.get(Property, item.property_id)
        summary = property_summary(prop).model_dump(mode="json") if prop else None
        output.append(SavedSearchMatchRead(id=item.id, saved_search_id=item.saved_search_id, property_id=item.property_id, match_score=item.match_score, current_price=item.current_price, matched_at=item.matched_at, notified_at=item.notified_at, property=summary))
    return output
