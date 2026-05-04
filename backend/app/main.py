"""
Samvaad 1092 — FastAPI Application Entry Point
=================================================
Asynchronous WebSocket server optimised for live call latency.

Endpoints:
    WS  /ws/call           — Primary call channel (audio + control)
    WS  /ws/call/{call_id} — Join an existing call session
    WS  /ws/dashboard      — Dashboard event stream (read-only)
    GET /api/health         — Liveness probe
    GET /api/sessions       — List active sessions (operator use)
    GET /api/session/{id}   — Get session details
    GET /api/history        — Call history from database
    GET /api/learning       — Learning signals (verified pairs)
    POST /api/agent-edit    — Save agent corrections
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.ws.call_handler import get_manager

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s │ %(name)-30s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("samvaad.main")


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("╔══════════════════════════════════════════╗")
    logger.info("║   SAMVAAD 1092 — Starting Up             ║")
    logger.info("║   Karnataka 1092 Helpline AI Layer        ║")
    logger.info("╚══════════════════════════════════════════╝")

    # Initialise database
    from app.core.database import init_db
    await init_db()
    logger.info("Database ready")

    yield
    logger.info("Samvaad 1092 shutting down")


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Samvaad 1092",
    description=(
        "Real-time voice-to-voice assistive layer for the Karnataka 1092 "
        "Helpline. Processes multilingual, dialect-rich, emotionally charged "
        "speech through a Verified Understanding pipeline."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.dashboard_origin, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# REST Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    """Liveness probe for load balancers and monitoring."""
    return {"status": "ok", "service": "samvaad-1092", "version": "0.2.0"}


@app.get("/api/sessions")
async def list_sessions():
    """List all active call sessions (operator dashboard)."""
    manager = get_manager()
    sessions = manager.active_sessions
    return {
        "count": len(sessions),
        "sessions": [
            {
                "call_id": s.call_id,
                "state": s.state,
                "distress_score": s.distress_score,
                "confidence": s.confidence,
                "language": s.language_detected,
                "started_at": s.started_at.isoformat(),
            }
            for s in sessions.values()
        ],
    }


@app.get("/api/session/{call_id}")
async def get_session(call_id: str):
    """Get full details for a specific call session."""
    manager = get_manager()
    session = manager.active_sessions.get(call_id)
    if session is None:
        return {"error": "Session not found"}, 404
    return session.model_dump()


@app.get("/api/history")
async def call_history(limit: int = 50):
    """Get historical call records from the database."""
    from app.core.database import get_call_history
    records = await get_call_history(limit=limit)
    return {"count": len(records), "records": records}


@app.get("/api/learning")
async def learning_signals(limit: int = 100):
    """Get verified learning signal pairs for continuous improvement."""
    from app.core.database import get_learning_signals
    signals = await get_learning_signals(limit=limit)
    return {"count": len(signals), "signals": signals}


@app.post("/api/agent-edit")
async def save_agent_edit(payload: dict):
    """Save agent corrections for a call (learning signal)."""
    call_id = payload.get("call_id", "")
    corrections = payload.get("corrections", {})
    if not call_id or not corrections:
        return {"error": "call_id and corrections required"}, 400

    from app.core.database import save_agent_edit as db_save
    success = await db_save(call_id, corrections)
    return {"success": success, "call_id": call_id}


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/call")
async def ws_call(ws: WebSocket):
    """
    Primary call channel — new call session.
    Accepts audio chunks, transcript text, and confirmation signals.
    """
    manager = get_manager()
    session = await manager.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            await manager.handle_message(ws, session, raw)
    except WebSocketDisconnect:
        await manager.disconnect(ws, session.call_id)


@app.websocket("/ws/call/{call_id}")
async def ws_call_join(ws: WebSocket, call_id: str):
    """Join an existing call session (e.g., supervisor monitoring)."""
    manager = get_manager()
    session = await manager.connect(ws, call_id=call_id)
    try:
        while True:
            raw = await ws.receive_text()
            await manager.handle_message(ws, session, raw)
    except WebSocketDisconnect:
        await manager.disconnect(ws, session.call_id)


@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    """
    Dashboard event stream — broadcasts all session events.
    Read-only: ignores incoming messages.
    """
    await ws.accept()
    # The dashboard WS is a passive listener; it receives broadcasts
    # through the ConnectionManager when connected to specific calls.
    # For a global feed, we could implement a pub/sub pattern here.
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level,
    )
