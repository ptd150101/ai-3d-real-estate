from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Property, SavedSearch, SavedSearchMatch, SavedSearchSubscription
from ..schemas import SearchFilters
from .notification import emit_event
from .search import search_properties


def get_or_create_subscription(db: Session, saved_search: SavedSearch) -> SavedSearchSubscription:
    item = db.scalar(select(SavedSearchSubscription).where(SavedSearchSubscription.saved_search_id == saved_search.id))
    if item: return item
    item = SavedSearchSubscription(saved_search_id=saved_search.id, is_active=saved_search.notify)
    db.add(item); db.flush(); return item


def normalized_filters(filters_json: dict) -> SearchFilters:
    allowed = set(SearchFilters.model_fields); values = {k: v for k, v in filters_json.items() if k in allowed and v not in ("", None)}
    for key in ("district", "property_type", "legal_status", "furnishing"):
        if key in values and isinstance(values[key], str): values[key] = [values[key]]
    for key in ("min_price", "max_price", "bedrooms", "bathrooms"):
        if key in values: values[key] = int(values[key])
    for key in ("min_area", "max_area", "radius_km", "latitude", "longitude"):
        if key in values: values[key] = float(values[key])
    for key in ("has_3d", "is_owner_listing"):
        if key in values and isinstance(values[key], str): values[key] = values[key].lower() in {"true", "1", "yes"}
    return SearchFilters(**values)


def due_for_digest(subscription: SavedSearchSubscription, now: datetime) -> bool:
    if subscription.frequency == "immediate": return True
    if subscription.frequency == "off" or not subscription.is_active: return False
    if not subscription.last_notified_at: return True
    last = subscription.last_notified_at if subscription.last_notified_at.tzinfo else subscription.last_notified_at.replace(tzinfo=timezone.utc)
    return now - last >= (timedelta(days=7) if subscription.frequency == "weekly" else timedelta(days=1))


def match_saved_search(db: Session, saved_search_id: str, *, notify: bool = True) -> dict:
    saved = db.get(SavedSearch, saved_search_id)
    if not saved: return {"status": "missing", "new_matches": 0}
    subscription = get_or_create_subscription(db, saved)
    if not subscription.is_active or subscription.frequency == "off": return {"status": "inactive", "new_matches": 0}
    items, _ = search_properties(db, normalized_filters(saved.filters_json), page=1, page_size=48)
    newly_created: list[Property] = []
    price_drops: list[Property] = []
    for property_obj in items:
        existing = db.scalar(select(SavedSearchMatch).where(SavedSearchMatch.saved_search_id == saved.id, SavedSearchMatch.property_id == property_obj.id))
        if existing:
            if subscription.notify_price_drop and existing.current_price and property_obj.price < existing.current_price:
                existing.current_price = property_obj.price; existing.notified_at = None; price_drops.append(property_obj)
            continue
        try:
            with db.begin_nested():
                db.add(SavedSearchMatch(saved_search_id=saved.id, property_id=property_obj.id, current_price=property_obj.price))
                db.flush()
            newly_created.append(property_obj)
        except IntegrityError:
            pass
    now = datetime.now(timezone.utc); subscription.last_checked_at = now
    pending = list(db.scalars(select(SavedSearchMatch).where(SavedSearchMatch.saved_search_id == saved.id, SavedSearchMatch.notified_at.is_(None)).order_by(SavedSearchMatch.matched_at)))
    notify_items = [db.get(Property, x.property_id) for x in pending]
    notify_items = [x for x in notify_items if x and x.status == "published"]
    should_notify = notify and notify_items and due_for_digest(subscription, now)
    if should_notify:
        ids = sorted(x.id for x in notify_items)
        emit_event(db, event_type="saved_search.match", aggregate_type="saved_search", aggregate_id=saved.id, recipients=[saved.user_id], payload={"count": len(ids), "search_name": saved.name, "property_ids": ids, "price_drop_count": len(price_drops)}, idempotency_key=f"saved-search:{saved.id}:{subscription.frequency}:{now.date().isoformat()}:{','.join(ids)}")
        db.query(SavedSearchMatch).filter(SavedSearchMatch.id.in_([x.id for x in pending])).update({"notified_at": now}, synchronize_session=False)
        subscription.last_notified_at = now
    db.commit()
    return {"status": "completed", "new_matches": len(newly_created), "price_drops": len(price_drops), "pending_notifications": len(pending), "notified": bool(should_notify), "property_ids": [x.id for x in newly_created]}


def match_all_saved_searches(db: Session) -> dict:
    ids = list(db.scalars(select(SavedSearch.id))); total = 0; notified = 0
    for search_id in ids:
        result = match_saved_search(db, search_id); total += int(result.get("new_matches", 0)); notified += int(bool(result.get("notified")))
    return {"saved_searches": len(ids), "new_matches": total, "digests_sent": notified}
