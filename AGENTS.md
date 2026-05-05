# Samvaad 1092 - Agent Instructions

This repository is a monorepo consisting of a Python FastAPI backend and a React/Vite dashboard, built for the "AI for Bharat" Samvaad 1092 emergency helpline.

## Architecture & Layout
- **`backend/`**: Python 3.12+ FastAPI application handling WebSocket audio streams, PII scrubbing, Acoustic Guardian distress detection, and Swarm LLM routing.
- **`dashboard/`**: Node.js 18+ Vite/React 19 application providing the operator interface.
- **`.env`**: Must be located at the **project root** (copy from `.env.example`).
- **Database**: SQLite (via `aiosqlite`) is used locally to store "Learning Signals" (verified logs/operator edits).

## Important Commands & Execution Flow

### Backend (`cd backend`)
- **Setup**: `python -m venv .venv` -> activate -> `pip install -r requirements.txt`
- **Run Dev Server**: `uvicorn app.main:app --reload` (Runs on `http://localhost:8000`)
- **Test**: Run `pytest` (uses `pytest` and `pytest-asyncio`).

### Dashboard (`cd dashboard`)
- **Setup**: `npm install`
- **Run Dev Server**: `npm run dev` (Runs on `http://localhost:5173`)
- **Build**: `npm run build`

## Key Workflows & Data Flow
- **WebSocket Streaming**: The dashboard streams audio via `ws://localhost:8000/ws/call`.
- **Security Priority**: PII Scrubbing (Regex + `ai4bharat/IndicNER`) and Acoustic Guardian analysis **always occur locally** before any data is sent to external LLMs.
- **Learning Signals**: Operator edits in the UI ("Agent Corrections" or "Manual Takeover") are posted to `http://localhost:8000/api/learning` to persist feedback loops.
- **State Machine**: The system operates as a pipeline: `Audio Input -> Scrub PII -> Classification -> Human Verification -> Dispatch`. High acoustic distress automatically bypasses verification to trigger `SAFE_HUMAN_TAKEOVER`.
