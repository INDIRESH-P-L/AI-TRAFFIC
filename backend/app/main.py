"""TRAFFICINTEL AI - Main Application Server

Real-Time AI Traffic Intelligence & Adaptive Signal Management Platform
Clean startup: initializes schema, verifies database connectivity, mounts API v1 and WebSocket gateway.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import time
import uuid

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy import text

from app.core.config import settings, INSECURE_DEFAULT_SECRET_KEY
from app.core.database import engine, Base, SessionLocal
from app.core.migrations import check_schema_is_current
from app.api.v1.router import api_router
from app.api.v1.websocket import ws_manager, websocket_gateway
from app.copilot.knowledge_rag import KnowledgeRAGEngine
from app.governance.ledger import install_listener as install_ledger_listener
from app.governance.rate_limit import policy_for_request, rate_limiter
from app.ingest.poller import controller_poller
from app.ingest.lease import release as release_poll_lease
from app.observability.logging import configure_logging, request_context
from app.observability.metrics import metrics_registry, render_prometheus
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trafficintel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify the schema matches the models, then index standards.
    # Alembic owns the schema; the API verifies rather than mutating it, so a
    # drifted database is reported here instead of failing inside a request.
    configure_logging(
        level="DEBUG" if settings.DEBUG else "INFO",
        structured=settings.STRUCTURED_LOGGING,
    )

    # Chain every audit entry at the session boundary, so a new endpoint
    # cannot forget to do it.
    install_ledger_listener()

    logger.info("Verifying TRAFFICINTEL AI relational schema...")
    schema_ok, schema_message = check_schema_is_current()
    if schema_ok:
        logger.info("%s", schema_message)
    elif settings.ENVIRONMENT.lower() == "production":
        raise RuntimeError("Refusing to start on a drifted schema. " + schema_message)
    else:
        logger.warning("SCHEMA DRIFT: %s", schema_message)
        logger.warning("Run 'python -m app.db_init' to bring the database up to date.")

    
    db = SessionLocal()
    try:
        KnowledgeRAGEngine.seed_initial_standards(db)
        logger.info("Traffic engineering standards and SOP documents indexed in RAG knowledge base.")
    finally:
        db.close()
    
    if settings.SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
        logger.warning(
            "SECRET_KEY is the published placeholder value. Issued JWTs are forgeable by anyone "
            "with a copy of this repository. Set SECRET_KEY in .env before exposing this instance."
        )

    if settings.CONTROLLER_POLL_ENABLED:
        controller_poller.interval_sec = settings.CONTROLLER_POLL_INTERVAL_SEC
        controller_poller.start()
        logger.info(
            "Controller polling enabled at %.1fs. Observed phase state is recorded "
            "for signal performance measures.",
            settings.CONTROLLER_POLL_INTERVAL_SEC,
        )
    else:
        logger.info(
            "Controller polling is disabled. Arrival-on-green, split failures and "
            "progression cannot be computed without observed signal state."
        )

    logger.info("TRAFFICINTEL AI backend initialized successfully. System state: READY.")
    yield

    await controller_poller.stop()

    # Hand the poll lease back explicitly. Without this a peer waits a full
    # lease TTL before taking over, and the network goes unobserved for that
    # window on every rolling restart.
    db = SessionLocal()
    try:
        if release_poll_lease(db):
            logger.info("Released the controller poll lease for handover.")
    except Exception as exc:  # noqa: BLE001 - shutdown must not fail on this
        logger.warning("Could not release the poll lease: %s", exc)
    finally:
        db.close()

    logger.info("Shutting down TRAFFICINTEL AI server...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Real-Time AI Traffic Intelligence & Adaptive Signal Management Platform",
    version=settings.VERSION,
    lifespan=lifespan
)

# CORS Configuration
# Explicit origin allow-list: a wildcard cannot be combined with credentialed
# requests (browsers reject the pair), and the console sends bearer tokens.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1
app.include_router(api_router, prefix=settings.API_V1_STR)


# Real-time WebSocket Gateway.
# Authenticated via the `token` query parameter: browsers cannot set headers on
# a WebSocket handshake, and an unauthenticated socket must never receive an
# operational event.
@app.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    await websocket_gateway(websocket, token)




# ---------------------------------------------------------------------------
# Observability & rate limiting middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def observability_and_limits(request: Request, call_next):
    """Assigns a trace id, records metrics, and enforces rate limits."""
    trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    started = time.perf_counter()

    # Identity for rate limiting: the API key or bearer subject when present,
    # else the client address. Falling back to the address means a shared NAT
    # shares a bucket, which is stated rather than silently assumed.
    identity = (
        request.headers.get("X-API-Key")
        or request.headers.get("Authorization", "")
        or (request.client.host if request.client else "unknown")
    )[:120]

    policy = policy_for_request(request.method, request.url.path)
    allowed, limit_headers = rate_limiter.check(identity, policy)

    if not allowed:
        metrics_registry.increment(
            "http_requests_total",
            {"method": request.method, "status": "429", "policy": policy.name},
        )
        response = JSONResponse(
            status_code=429,
            content={
                "detail": (
                    "Rate limit exceeded for policy '{}': {} requests per {:.0f}s. {}"
                    .format(policy.name, policy.max_requests, policy.window_sec,
                            policy.description)
                ),
                "policy": policy.name,
                "trace_id": trace_id,
            },
        )
        for key, value in limit_headers.items():
            response.headers[key] = str(value)
        response.headers["X-Request-ID"] = trace_id
        return response

    with request_context(trace_id=trace_id, path=request.url.path, method=request.method):
        try:
            response = await call_next(request)
        except Exception:
            metrics_registry.increment(
                "http_requests_total",
                {"method": request.method, "status": "500", "policy": policy.name},
            )
            raise

    duration = time.perf_counter() - started
    metrics_registry.increment(
        "http_requests_total",
        {"method": request.method, "status": str(response.status_code), "policy": policy.name},
    )
    metrics_registry.observe("http_request_duration_seconds", duration, {"method": request.method})

    for key, value in limit_headers.items():
        response.headers[key] = str(value)
    response.headers["X-Request-ID"] = trace_id
    return response


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus exposition. Counters only; no traffic measurements here."""
    return Response(content=render_prometheus(), media_type="text/plain; version=0.0.4")


# Health & Observability Probes
@app.get("/health")
def health_check():
    """Reports measured subsystem state. Never asserts health it has not verified."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database_status = "CONNECTED"
        database_dialect = engine.dialect.name
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator verbatim
        logger.error("Database health probe failed: %s", exc)
        database_status = "UNREACHABLE"
        database_dialect = engine.dialect.name

    return {
        "status": "HEALTHY" if database_status == "CONNECTED" else "DEGRADED",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "database": database_status,
        "database_dialect": database_dialect,
        "checked_at": datetime.now(timezone.utc).isoformat()
    }


@app.get("/ready")
def readiness_check():
    return {"status": "READY"}


@app.get("/live")
def liveness_check():
    return {"status": "LIVE"}


@app.get("/")
def root():
    return {
        "product": settings.PROJECT_NAME,
        "tagline": settings.TAGLINE,
        "version": settings.VERSION,
        "documentation": "/docs",
        "api_v1": settings.API_V1_STR,
        "status": "SYSTEM_READY"
    }
