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
    logger.info("║   Karnataka 1092 Helpline AI Layer       ║")
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

@app.get("/api/analytics/overview")
async def get_analytics_overview_api():
    """Get high-level analytics for the dashboard overview."""
    from app.core.database import get_analytics_overview
    return await get_analytics_overview()


@app.get("/api/grievances")
async def get_grievances(limit: int = 100):
    """Alias for history to power the grievance inbox view."""
    from app.core.database import get_call_history
    records = await get_call_history(limit=limit)
    return {"count": len(records), "records": records}


@app.post("/api/grievances/{call_id}/resolve")
async def resolve_grievance_api(call_id: str):
    """Mark a grievance as resolved."""
    from app.core.database import resolve_grievance
    success = await resolve_grievance(call_id)
    if not success:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Call record not found")
    return {"success": True, "call_id": call_id, "status": "RESOLVED"}

@app.get("/api/ml/status")
async def ml_status_api():
    """Get the active learning status."""
    from app.core.database import get_unapplied_training_data
    unapplied = await get_unapplied_training_data()
    return {
        "pending_corrections": len(unapplied),
        "status": "ready" if len(unapplied) > 0 else "up_to_date"
    }

@app.post("/api/ml/retrain")
async def ml_retrain_api():
    """Trigger a hot-reload active learning cycle."""
    from app.core.database import get_unapplied_training_data, mark_training_data_applied
    from app.core.ml_routing import retrain_classifier
    
    unapplied = await get_unapplied_training_data()
    if not unapplied:
        return {"success": True, "message": "No new data to train on."}
        
    # Retrain the model
    success = retrain_classifier(unapplied)
    if success:
        # Mark as applied so we don't train on them again unnecessarily 
        # (Though our retrain_classifier script reloads all base data anyway)
        await mark_training_data_applied([r["id"] for r in unapplied])
        return {"success": True, "message": f"Successfully trained on {len(unapplied)} new edge cases."}
    
    from fastapi import HTTPException
    raise HTTPException(status_code=500, detail="Model retraining failed")


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
    await ws.accept()
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
    await ws.accept()
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
    Also allows the dashboard to send commands (takeover, agent_edit) to specific calls.
    """
    from app.ws.call_handler import get_manager
    manager = get_manager()
    await manager.connect_dashboard(ws)
    try:
        while True:
            text = await ws.receive_text()
            try:
                import json
                data = json.loads(text)
                call_id = data.get("call_id")
                if call_id:
                    session = manager.active_sessions.get(call_id)
                    if session:
                        await manager.handle_message(ws, session, text)
            except Exception as exc:
                pass
    except WebSocketDisconnect:
        await manager.disconnect_dashboard(ws)


from fastapi import Request
from fastapi.responses import HTMLResponse

@app.post("/api/twiml")
async def twilio_webhook(request: Request):
    """
    Twilio Webhook: Returns TwiML XML instructing Twilio to connect
    the phone call to our WebSocket stream.
    """
    # Extract the host dynamically from the request headers to support ngrok
    host = request.headers.get("host")
    protocol = "wss" if "ngrok" in host or "https" in str(request.url) else "ws"
    ws_url = f"{protocol}://{host}/ws/twilio"
    
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say voice="Polly.Aditi">Welcome to the Karnataka 1 0 9 2 Helpline. Speak in English, Hindi mein boliye, or Kannada-dalli maathanaadi, after the tone.</Say>
        <Play digits="0"></Play>
        <Connect>
            <Stream url="{ws_url}" />
        </Connect>
    </Response>"""
    return HTMLResponse(content=xml, media_type="application/xml")


@app.websocket("/ws/twilio")
async def ws_twilio(ws: WebSocket):
    """
    Twilio Media Stream WebSocket Handler.
    """
    from app.ws.twilio_handler import TwilioMediaStreamHandler
    handler = TwilioMediaStreamHandler(ws)
    await handler.handle()


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
