from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, SessionLocal, engine
from .logging_config import configure_logging
from .routers import (
    admin, analytics, auth, calendar, chat, crm, engagement, experience, health, jobs,
    knowledge, legal, messaging, notifications, projects_agents, properties, reviews, uploads,
)
from .seed import seed_database
from .services.rate_limit import SlidingWindowRateLimiter
from .services.messaging import manager as messaging_manager

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("nestora.api")
rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db: seed_database(db)
    await messaging_manager.start()
    yield
    await messaging_manager.stop()


app = FastAPI(title=settings.app_name, version="1.1.0", description="AI-assisted real-estate marketplace with P1 notifications, realtime messaging, CRM, panorama, legal workflow and analytics.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    rate_key = f"{request.client.host if request.client else 'unknown'}:{request.url.path}"
    sensitive_prefixes = [f"{settings.api_prefix}/chat", f"{settings.api_prefix}/messages", f"{settings.api_prefix}/analytics/events"]
    if any(request.url.path.startswith(x) for x in sensitive_prefixes) and not rate_limiter.allow(rate_key):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}, headers={"x-request-id": request_id})
    try: response = await call_next(request)
    except HTTPException: raise
    except Exception:
        logger.exception("unhandled request error", extra={"request_id": request_id, "method": request.method, "path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=(self), gyroscope=(self)"
    logger.info("request complete", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((time.perf_counter()-started)*1000, 2)})
    return response


for router in [
    auth.router, properties.router, projects_agents.router, engagement.router, chat.router,
    knowledge.router, uploads.router, jobs.router, admin.router, notifications.router,
    calendar.router, reviews.router, messaging.router, crm.router, experience.router,
    legal.router, analytics.router,
]:
    app.include_router(router, prefix=settings.api_prefix)
app.include_router(health.router)
app.mount("/storage", StaticFiles(directory=str(settings.storage_path), check_dir=False), name="storage")


@app.get("/")
def root(): return {"name": settings.app_name, "version": "1.1.0", "docs": "/docs", "health": "/health"}
