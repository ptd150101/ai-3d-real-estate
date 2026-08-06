from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, SessionLocal, engine
from .logging_config import configure_logging
from .routers import (
    admin,
    analytics,
    auth,
    calendar,
    chat,
    crm,
    demo_assets,
    engagement,
    experience,
    health,
    jobs,
    knowledge,
    legal,
    messaging,
    notifications,
    p2_contracts,
    p2_intelligence,
    p2_mlops,
    p2_mobile,
    p2_organizations,
    p2_payments,
    p2_spatial,
    projects_agents,
    properties,
    reviews,
    uploads,
)
from .seed import seed_database
from .services.messaging import manager as messaging_manager
from .services.rate_limit import SlidingWindowRateLimiter

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("nestora.api")
rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_production()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    settings.reconstruction_work_path.mkdir(parents=True, exist_ok=True)
    # Production schema changes are migration-only. create_all remains useful for
    # isolated tests and developer fixtures where Alembic is intentionally absent.
    if settings.environment.lower() not in {"production", "prod"}:
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    await messaging_manager.start()
    try:
        yield
    finally:
        await messaging_manager.stop()


app = FastAPI(
    title=settings.app_name,
    version="2.2.0",
    description="Multi-agency AI and immersive real-estate marketplace with deterministic demo data, live provider adapters, ML serving, reconstruction, AR/VR and mobile.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    storage_parts = (
        PurePosixPath(request.url.path).parts if request.url.path.startswith("/storage") else ()
    )
    if "private" in storage_parts:
        return JSONResponse(
            status_code=404,
            content={"detail": "Not found"},
            headers={"x-request-id": request_id, "cache-control": "no-store"},
        )
    rate_key = f"{request.client.host if request.client else 'unknown'}:{request.url.path}"
    sensitive_prefixes = [
        f"{settings.api_prefix}/chat",
        f"{settings.api_prefix}/messages",
        f"{settings.api_prefix}/analytics/events",
        f"{settings.api_prefix}/payments/webhooks",
        f"{settings.api_prefix}/contracts/webhooks",
        f"{settings.api_prefix}/mobile/auth",
    ]
    if any(request.url.path.startswith(prefix) for prefix in sensitive_prefixes) and not rate_limiter.allow(rate_key):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"x-request-id": request_id},
        )
    try:
        response = await call_next(request)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "unhandled request error",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    response.headers["permissions-policy"] = (
        "camera=(self), microphone=(), geolocation=(self), gyroscope=(self), "
        "accelerometer=(self), magnetometer=(self), xr-spatial-tracking=(self)"
    )
    logger.info(
        "request complete",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return response


for router in [
    auth.router,
    properties.router,
    projects_agents.router,
    engagement.router,
    chat.router,
    knowledge.router,
    uploads.router,
    jobs.router,
    admin.router,
    notifications.router,
    calendar.router,
    reviews.router,
    messaging.router,
    crm.router,
    experience.router,
    legal.router,
    analytics.router,
    p2_organizations.router,
    p2_payments.router,
    p2_contracts.router,
    p2_intelligence.router,
    p2_spatial.router,
    p2_mobile.router,
    p2_mlops.router,
    demo_assets.router,
]:
    app.include_router(router, prefix=settings.api_prefix)
app.include_router(health.router)
app.mount("/storage", StaticFiles(directory=str(settings.storage_path), check_dir=False), name="storage")


@app.get("/")
def root():
    return {"name": settings.app_name, "version": "2.2.0", "docs": "/docs", "health": "/health"}
