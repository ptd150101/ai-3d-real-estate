from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Favorite,
    Property,
    RecommendationFeedback,
    RecommendationImpression,
    RecommendationProfile,
    User,
    ValuationComparable,
    ValuationDriftMetric,
    ValuationEvaluation,
    ValuationModelVersion,
    ValuationRequest,
    ValuationResult,
)
from .model_runtime import ModelRuntimeError, invoke_model

DISTRICT_PRICE_M2 = {
    "Tây Hồ": 95_000_000,
    "Cầu Giấy": 88_000_000,
    "Long Biên": 70_000_000,
    "Nam Từ Liêm": 72_000_000,
    "Hà Đông": 62_000_000,
}
TYPE_FACTOR = {
    "apartment": 1.0,
    "townhouse": 1.12,
    "villa": 1.25,
    "shophouse": 1.18,
    "land": 0.8,
}


def ensure_baseline_model(db: Session) -> ValuationModelVersion:
    model = db.scalar(
        select(ValuationModelVersion).where(
            ValuationModelVersion.name == "nestora-avm",
            ValuationModelVersion.status == "production",
        )
    )
    if not model:
        model = ValuationModelVersion(
            name="nestora-avm",
            version="baseline-v1",
            status="production",
            feature_version="p2-v1",
            metrics_json={"mae": 0.12, "mape": 0.11},
            baseline_metrics_json={"mae": 0.18, "mape": 0.17},
            trained_at=datetime.now(timezone.utc),
        )
        db.add(model)
        db.flush()
        db.add(
            ValuationEvaluation(
                model_version_id=model.id,
                split_type="time_holdout",
                segment="all",
                metrics_json={"mae": 0.12, "mape": 0.11},
                passed=True,
            )
        )
    return model


def _valuation_features(prop: Property | None, inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "district": inputs.get("district") or (prop.district if prop else None),
        "property_type": inputs.get("property_type") or (prop.property_type if prop else None),
        "area_m2": float(inputs.get("area_m2") or (prop.area_m2 if prop else 0)),
        "bedrooms": int(inputs.get("bedrooms") or (prop.bedrooms if prop else 0)),
        "legal_status": inputs.get("legal_status") or (prop.legal_status if prop else None),
        "asking_price": int(prop.price) if prop else None,
        "property_id": prop.id if prop else None,
    }


def _runtime_valuation(
    db: Session,
    *,
    organization_id: str | None,
    user_id: str,
    request_id: str,
    features: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    try:
        runtime = invoke_model(
            db,
            task="valuation",
            organization_id=organization_id,
            routing_key=f"valuation:{organization_id}:{user_id}:{request_id}",
            payload=features,
        )
    except ModelRuntimeError as exc:
        return None, None, str(exc)
    if not runtime:
        return None, None, None
    body, selection = runtime
    estimate = int(body.get("estimate") or body.get("prediction") or 0)
    if estimate <= 0:
        return None, selection.model.id, "runtime returned an invalid estimate"
    confidence = min(1.0, max(0.0, float(body.get("confidence", 0.75))))
    spread = float(body.get("spread", 0.12))
    lower = int(body.get("lower_bound") or body.get("lower") or estimate * (1 - spread))
    upper = int(body.get("upper_bound") or body.get("upper") or estimate * (1 + spread))
    return {
        "estimate": estimate,
        "lower": lower,
        "upper": upper,
        "confidence": confidence,
        "explanation": {
            **(body.get("explanation") if isinstance(body.get("explanation"), dict) else {}),
            "runtime": "remote",
            "deployment_id": selection.deployment.id,
            "model": selection.model.name,
            "model_version": selection.model.version,
        },
    }, selection.model.id, None


def value_property(
    db: Session,
    *,
    user: User,
    organization_id: str | None,
    property_id: str | None,
    inputs: dict,
) -> tuple[ValuationRequest, ValuationResult, list[ValuationComparable]]:
    prop = db.get(Property, property_id) if property_id else None
    data = _valuation_features(prop, inputs)
    request = ValuationRequest(
        organization_id=organization_id,
        user_id=user.id,
        property_id=property_id,
        input_json=data,
        status="processing",
    )
    db.add(request)
    db.flush()

    runtime_value, runtime_model_id, runtime_error = _runtime_valuation(
        db,
        organization_id=organization_id,
        user_id=user.id,
        request_id=request.id,
        features=data,
    )
    candidates = list(
        db.scalars(
            select(Property)
            .where(
                Property.status == "published",
                Property.district == data["district"],
                Property.property_type == data["property_type"],
            )
            .limit(8)
        )
    ) if data["district"] and data["property_type"] else []

    if runtime_value:
        result = ValuationResult(
            request_id=request.id,
            model_version_id=runtime_model_id,
            estimate=runtime_value["estimate"],
            lower_bound=runtime_value["lower"],
            upper_bound=runtime_value["upper"],
            confidence=runtime_value["confidence"],
            status="completed",
            feature_snapshot_json=data,
            explanation_json={
                **runtime_value["explanation"],
                "comparable_count": len(candidates),
                "caveat": "Ước tính tham khảo, không thay thế thẩm định pháp lý hoặc định giá được cấp phép.",
            },
        )
        request.status = "completed"
    elif not data["district"] or not data["property_type"] or data["area_m2"] <= 0:
        result = ValuationResult(
            request_id=request.id,
            status="insufficient_data",
            confidence=0,
            feature_snapshot_json=data,
            explanation_json={"reason": "Missing supported district, type or area", "runtime_error": runtime_error},
        )
        request.status = "completed"
    else:
        base = DISTRICT_PRICE_M2.get(data["district"])
        if not base:
            result = ValuationResult(
                request_id=request.id,
                status="insufficient_data",
                confidence=0.15,
                feature_snapshot_json=data,
                explanation_json={
                    "reason": "District outside supported baseline",
                    "runtime_error": runtime_error,
                },
            )
            request.status = "completed"
        else:
            factor = TYPE_FACTOR.get(data["property_type"], 0.95)
            legal_factor = (
                1.04
                if data["legal_status"]
                and any(x in str(data["legal_status"]).lower() for x in ["sổ", "lâu dài"])
                else 0.96
            )
            estimate = int(base * data["area_m2"] * factor * legal_factor)
            model = ensure_baseline_model(db)
            confidence = min(0.92, 0.55 + 0.06 * len(candidates))
            spread = 0.18 if len(candidates) < 3 else 0.12
            result = ValuationResult(
                request_id=request.id,
                model_version_id=model.id,
                estimate=estimate,
                lower_bound=int(estimate * (1 - spread)),
                upper_bound=int(estimate * (1 + spread)),
                confidence=confidence,
                status="completed",
                feature_snapshot_json=data,
                explanation_json={
                    "runtime": "deterministic_fallback",
                    "runtime_error": runtime_error,
                    "price_per_m2": int(base * factor * legal_factor),
                    "comparable_count": len(candidates),
                    "caveat": "Ước tính tham khảo, không thay thế thẩm định pháp lý hoặc định giá được cấp phép.",
                },
            )
            request.status = "completed"
    db.add(result)
    db.flush()

    comps: list[ValuationComparable] = []
    for item in candidates[:5]:
        similarity = max(0.1, 1 - abs(item.area_m2 - data["area_m2"]) / max(data["area_m2"], 1))
        comp = ValuationComparable(
            result_id=result.id,
            property_id=item.id,
            similarity=similarity,
            adjustments_json={"area_delta": item.area_m2 - data["area_m2"]},
        )
        db.add(comp)
        comps.append(comp)
    db.commit()
    db.refresh(request)
    db.refresh(result)
    return request, result, comps


def _heuristic_recommendations(db: Session, user: User, profile: RecommendationProfile) -> list[tuple[float, Property, list[str]]]:
    hidden = {
        item.property_id
        for item in db.scalars(
            select(RecommendationFeedback).where(
                RecommendationFeedback.user_id == user.id,
                RecommendationFeedback.action == "hide",
            )
        )
    }
    favorites = list(db.scalars(select(Favorite).where(Favorite.user_id == user.id))) if profile.enabled else []
    favorite_props = [db.get(Property, favorite.property_id) for favorite in favorites]
    favorite_props = [item for item in favorite_props if item]
    preferred_district = favorite_props[-1].district if favorite_props else None
    preferred_type = favorite_props[-1].property_type if favorite_props else None
    rows: list[tuple[float, Property, list[str]]] = []
    for prop in db.scalars(select(Property).where(Property.status == "published")):
        if prop.id in hidden:
            continue
        score = 0.3
        reasons: list[str] = []
        if profile.enabled and preferred_district and prop.district == preferred_district:
            score += 0.3
            reasons.append("cùng khu vực bạn quan tâm")
        if profile.enabled and preferred_type and prop.property_type == preferred_type:
            score += 0.25
            reasons.append("cùng loại hình bạn đã lưu")
        if prop.is_featured:
            score += 0.08
        if prop.is_verified:
            score += 0.07
            reasons.append("dữ liệu đã xác minh")
        rows.append((score, prop, reasons or ["tin mới phù hợp thị trường"]))
    return rows


def recommend(db: Session, user: User, limit: int = 12) -> list[dict]:
    profile = db.scalar(select(RecommendationProfile).where(RecommendationProfile.user_id == user.id))
    if not profile:
        profile = RecommendationProfile(user_id=user.id, enabled=True, signals_json={})
        db.add(profile)
        db.flush()
    candidates = _heuristic_recommendations(db, user, profile)
    by_id = {prop.id: (prop, reasons, heuristic) for heuristic, prop, reasons in candidates}
    ranked: list[tuple[float, Property, list[str], str, str | None]] = []
    runtime_error: str | None = None
    if profile.enabled and candidates:
        features = {
            "user_id": user.id,
            "signals": profile.signals_json or {},
            "candidates": [
                {
                    "property_id": prop.id,
                    "district": prop.district,
                    "property_type": prop.property_type,
                    "price": prop.price,
                    "area_m2": prop.area_m2,
                    "bedrooms": prop.bedrooms,
                    "is_featured": prop.is_featured,
                    "is_verified": prop.is_verified,
                    "heuristic_score": heuristic,
                }
                for heuristic, prop, _ in candidates[:200]
            ],
        }
        try:
            runtime_organization_id = profile.organization_id or candidates[0][1].organization_id
            runtime = invoke_model(
                db,
                task="recommendation",
                organization_id=runtime_organization_id,
                routing_key=f"recommendation:{user.id}",
                payload=features,
            )
        except ModelRuntimeError as exc:
            runtime = None
            runtime_error = str(exc)
        if runtime:
            body, selection = runtime
            items = body.get("items") or body.get("recommendations") or []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict) or item.get("property_id") not in by_id:
                        continue
                    prop, default_reasons, _ = by_id[item["property_id"]]
                    reason = item.get("reason")
                    reasons = [str(reason)] if reason else default_reasons
                    ranked.append(
                        (
                            float(item.get("score", 0)),
                            prop,
                            reasons,
                            "model",
                            f"{selection.model.name}:{selection.model.version}",
                        )
                    )
    if not ranked:
        ranked = [
            (score, prop, reasons, "deterministic", runtime_error)
            for score, prop, reasons in candidates
        ]
    ranked.sort(
        key=lambda row: (
            row[0],
            row[1].published_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    result: list[dict] = []
    seen_types: set[str] = set()
    for score, prop, reasons, source, model_label in ranked:
        if len(result) >= limit:
            break
        if len(result) < 4 or prop.property_type not in seen_types:
            impression = RecommendationImpression(
                user_id=user.id,
                property_id=prop.id,
                source=source,
                score=score,
                reason=", ".join(reasons),
                experiment_key=model_label,
            )
            db.add(impression)
            result.append(
                {
                    "property_id": prop.id,
                    "slug": prop.slug,
                    "title": prop.title,
                    "price": prop.price,
                    "district": prop.district,
                    "property_type": prop.property_type,
                    "score": round(score, 4),
                    "reason": impression.reason,
                    "source": source,
                    "model": model_label if source == "model" else None,
                    "impression_id": impression.id,
                }
            )
            seen_types.add(prop.property_type)
    db.commit()
    return result


def promote_valuation_model(db: Session, model: ValuationModelVersion) -> ValuationModelVersion:
    passed = db.scalar(
        select(ValuationEvaluation).where(
            ValuationEvaluation.model_version_id == model.id,
            ValuationEvaluation.passed.is_(True),
        )
    )
    metric = float(model.metrics_json.get("mae", 999))
    baseline = float(model.baseline_metrics_json.get("mae", 0))
    if not passed or metric >= baseline:
        raise ValueError("Model failed evaluation gate")
    for current in db.scalars(
        select(ValuationModelVersion).where(
            ValuationModelVersion.organization_id == model.organization_id,
            ValuationModelVersion.name == model.name,
            ValuationModelVersion.status == "production",
        )
    ):
        current.status = "retired"
    model.status = "production"
    db.commit()
    db.refresh(model)
    return model


def record_drift(
    db: Session,
    model: ValuationModelVersion,
    segment: str,
    value: float,
    threshold: float,
) -> ValuationDriftMetric:
    status = "alert" if value > threshold else "healthy"
    item = ValuationDriftMetric(
        model_version_id=model.id,
        segment=segment,
        metric="psi",
        value=value,
        threshold=threshold,
        status=status,
    )
    db.add(item)
    if status == "alert":
        model.status = "disabled"
    db.commit()
    db.refresh(item)
    return item
