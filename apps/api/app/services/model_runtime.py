from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MLArtifact, MLDeployment, MLModelVersion, MLUsageRecord


class ModelRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeSelection:
    deployment: MLDeployment
    model: MLModelVersion
    artifact: MLArtifact
    endpoint: str


def _endpoint(artifact: MLArtifact) -> str | None:
    metadata = artifact.metadata_json or {}
    endpoint = metadata.get("endpoint") or metadata.get("inference_url")
    if endpoint:
        return str(endpoint).rstrip("/")
    if str(artifact.uri).startswith(("http://", "https://")):
        return str(artifact.uri).rstrip("/")
    return None


def select_runtime(
    db: Session,
    *,
    task: str,
    organization_id: str | None,
    routing_key: str,
    environment: str = "production",
) -> RuntimeSelection | None:
    rows = list(
        db.execute(
            select(MLDeployment, MLModelVersion, MLArtifact)
            .join(MLModelVersion, MLDeployment.model_version_id == MLModelVersion.id)
            .join(MLArtifact, MLModelVersion.artifact_id == MLArtifact.id)
            .where(
                MLModelVersion.task == task,
                MLModelVersion.organization_id == organization_id,
                MLDeployment.environment == environment,
                MLDeployment.status == "active",
                MLDeployment.traffic_percent > 0,
            )
            .order_by(MLDeployment.started_at, MLDeployment.id)
        )
    )
    candidates: list[tuple[int, RuntimeSelection]] = []
    total = 0
    for deployment, model, artifact in rows:
        endpoint = _endpoint(artifact)
        if not endpoint:
            continue
        weight = max(0, int(deployment.traffic_percent))
        total += weight
        candidates.append((total, RuntimeSelection(deployment, model, artifact, endpoint)))
    if not candidates or total <= 0:
        return None
    bucket = int(hashlib.sha256(routing_key.encode()).hexdigest()[:16], 16) % total
    for boundary, selection in candidates:
        if bucket < boundary:
            return selection
    return candidates[-1][1]


def invoke_model(
    db: Session,
    *,
    task: str,
    organization_id: str | None,
    routing_key: str,
    payload: dict[str, Any],
    environment: str = "production",
) -> tuple[dict[str, Any], RuntimeSelection] | None:
    selection = select_runtime(
        db,
        task=task,
        organization_id=organization_id,
        routing_key=routing_key,
        environment=environment,
    )
    if not selection:
        return None
    settings = get_settings()
    metadata = selection.artifact.metadata_json or {}
    headers = {"content-type": "application/json"}
    if metadata.get("authorization"):
        headers["authorization"] = str(metadata["authorization"])
    elif metadata.get("api_key"):
        headers[str(metadata.get("api_key_header") or "x-api-key")] = str(metadata["api_key"])
    request_body = {
        "task": task,
        "model": selection.model.name,
        "version": selection.model.version,
        "features": payload,
        "request_id": routing_key,
    }
    started = time.perf_counter()
    status = "succeeded"
    error: str | None = None
    try:
        with httpx.Client(timeout=settings.ml_inference_timeout_seconds) as client:
            response = client.post(selection.endpoint, json=request_body, headers=headers)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ModelRuntimeError("Inference endpoint returned a non-object response")
        return body, selection
    except Exception as exc:
        status = "failed"
        error = str(exc)[:1000]
        raise ModelRuntimeError(f"Inference failed for {selection.model.name}:{selection.model.version}: {exc}") from exc
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        db.add(
            MLUsageRecord(
                organization_id=organization_id,
                job_type=f"inference:{task}",
                units=1,
                cost_amount=float(metadata.get("cost_per_request", 0) or 0),
                metadata_json={
                    "deployment_id": selection.deployment.id,
                    "model_version_id": selection.model.id,
                    "status": status,
                    "latency_ms": latency_ms,
                    "error": error,
                },
            )
        )
        db.commit()


def check_deployment_health(
    db: Session,
    deployment: MLDeployment,
) -> dict[str, Any]:
    model = db.get(MLModelVersion, deployment.model_version_id)
    artifact = db.get(MLArtifact, model.artifact_id) if model and model.artifact_id else None
    if not model or not artifact:
        return {"healthy": False, "reason": "artifact_missing"}
    endpoint = _endpoint(artifact)
    if not endpoint:
        return {"healthy": False, "reason": "endpoint_missing"}
    metadata = artifact.metadata_json or {}
    health_url = str(metadata.get("health_url") or f"{endpoint.rstrip('/')}/health")
    headers: dict[str, str] = {}
    if metadata.get("authorization"):
        headers["authorization"] = str(metadata["authorization"])
    try:
        with httpx.Client(timeout=get_settings().ml_inference_timeout_seconds) as client:
            response = client.get(health_url, headers=headers)
            response.raise_for_status()
            body = response.json() if "application/json" in response.headers.get("content-type", "") else {}
        error_rate = float(body.get("error_rate", 0) or 0)
        healthy = bool(body.get("healthy", True)) and error_rate <= get_settings().ml_max_error_rate
        return {
            "healthy": healthy,
            "status_code": response.status_code,
            "error_rate": error_rate,
            "details": body,
        }
    except Exception as exc:
        return {"healthy": False, "reason": "health_request_failed", "error": str(exc)[:1000]}
