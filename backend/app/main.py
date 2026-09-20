"""TRAFFICINTEL AI - Main Application Server

Real-Time AI Traffic Intelligence & Adaptive Signal Management Platform
Clean startup: initializes schema, verifies database connectivity, mounts API v1 and WebSocket gateway.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.api.v1.router import api_router
from app.api.v1.websocket import ws_manager
from app.copilot.knowledge_rag import KnowledgeRAGEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trafficintel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables and seed initial engineering standards into RAG
    logger.info("Initializing TRAFFICINTEL AI relational schema...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        KnowledgeRAGEngine.seed_initial_standards(db)
        logger.info("Traffic engineering standards and SOP documents indexed in RAG knowledge base.")
    finally:
        db.close()
    
    logger.info("TRAFFICINTEL AI backend initialized successfully. System state: READY.")
    yield
    logger.info("Shutting down TRAFFICINTEL AI server...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Real-Time AI Traffic Intelligence & Adaptive Signal Management Platform",
    version=settings.VERSION,
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production deployments configure via settings.BACKEND_CORS_ORIGINS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1
app.include_router(api_router, prefix=settings.API_V1_STR)


# Real-time WebSocket Gateway
@app.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keepalive / ping reception
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# Health & Observability Probes
@app.get("/health")
def health_check():
    return {
        "status": "HEALTHY",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "database": "CONNECTED"
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
