# 🛡 Samvaad 1092

**Real-time Voice-to-Voice Assistive Layer for the Karnataka 1092 Helpline**

> *"Verified Understanding" for every emergency call — multilingual, distress-aware, privacy-first.*

Built for the **AI for Bharat 2 Hackathon**.

---

## 🎯 Mission

Karnataka's 1092 helpline handles domestic violence, elder abuse, and child distress calls across **three languages** (Kannada, Hindi, English) and dozens of dialects. Samvaad 1092 ensures that AI-assisted call handling achieves **Verified Understanding** before any action is taken — because in emergencies, misunderstanding is not an option.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OPERATOR DASHBOARD                           │
│  React + Vite + Tailwind  │  Monochrome Glassmorphism               │
│  [Transcript] [Distress Gauge] [Confidence Gauge] [State Timeline]  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ WebSocket (JSON frames)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FASTAPI WEBSOCKET SERVER                        │
│                      (Python 3.12 + async)                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │   ACOUSTIC   │  │     PII      │  │    VERIFICATION STATE    │   │
│  │   GUARDIAN   │  │   SCRUBBER   │  │        MACHINE           │   │
│  │              │  │              │  │                          │   │
│  │  librosa +   │  │  Regex +     │  │ INIT → LISTEN → SCRUB →  │   │
│  │  Wav2Vec2    │  │  IndicNER    │  │ ANALYZE → RESTATE →      │   │
│  │  (on-device) │  │  (on-device) │  │ CONFIRM → VERIFIED       │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘   │
│         │                 │                     │                   │
│         ▼                 ▼                     ▼                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              MODEL-AGNOSTIC LLM SWARM                        │   │
│  │  ┌────────┐    ┌────────────┐    ┌─────────────────┐         │   │
│  │  │  Groq  │ →  │  Gemini 3  │ →  │  DeepSeek       │         │   │
│  │  │ <500ms │    │   Flash    │    │  (OpenRouter)   │         │   │
│  │  │  fast  │    │  balanced  │    │  deep dialect   │         │   │
│  │  └────────┘    └────────────┘    └─────────────────┘         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  🔒 SECURITY: No raw PII ever leaves the device.                    │
│     All scrubbing happens locally before LLM calls.                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 The Verification State Machine

The heart of Samvaad 1092 is a strict finite state machine that ensures every piece of caller information is **verified** before action:

| State | Description | Transition |
|-------|-------------|------------|
| `INIT` | Call connected, system ready | → `LISTEN` |
| `LISTEN` | Receiving audio / transcript from caller | → `SCRUB` |
| `SCRUB` | PII redaction (Aadhaar, PAN, phone, names, locations) | → `ANALYZE` |
| `ANALYZE` | LLM cascade extracts sentiment, emergency type, cultural context | → `RESTATE` |
| `RESTATE` | AI generates a verification question in caller's language | → `WAIT_FOR_CONFIRM` |
| `WAIT_FOR_CONFIRM` | "I understand the issue is X, is that correct?" | → `VERIFIED` or → `LISTEN` |
| `VERIFIED` | ✅ Understanding confirmed — dispatch can proceed | Terminal |
| `HUMAN_TAKEOVER` | ⚠ Escalated to human agent (distress/low confidence) | Terminal |

**Emergency bypass:** If Acoustic Distress > 0.85 at _any_ point, the FSM jumps directly to `HUMAN_TAKEOVER` (SAFE_HUMAN_TAKEOVER event).

---

## 🛡 PII Scrubbing (Defence in Depth)

**Absolute rule: No hosted-LLM call ever sees raw PII.**

| Layer | Method | Catches |
|-------|--------|---------|
| **Layer 1** | Regex patterns | Aadhaar, PAN, phone, email, IFSC, vehicle reg, bank accounts |
| **Layer 2** | Transformer NER (`ai4bharat/IndicNER`) | Person names, locations, organisations (Kannada/Hindi/English) |

Both layers run **entirely on-device**. The scrubbed text replaces PII with tagged placeholders (e.g., `[AADHAAR_REDACTED]`, `[NAME_REDACTED]`).

---

## 🧠 LLM Cascade Logic

| Purpose | Primary | Fallback | Latency Target |
|---------|---------|----------|-----------------|
| **Sentiment** | Groq (LPU) | Gemini 3 Flash | < 500ms |
| **Analysis** | DeepSeek (OpenRouter) | Gemini → Groq | < 3s |
| **Restatement** | Gemini 3 Flash | Groq | < 1s |

The `ProviderFactory` supports **hot-swapping** providers at runtime. If one provider fails, the cascade automatically tries the next.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- API keys for at least one LLM provider (Gemini, Groq, or OpenRouter)

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/samvaad-1092.git
cd samvaad-1092
cp .env.example .env
# Edit .env with your API keys
```

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
python -m app.main
```

Server starts on `http://localhost:8000`.

### 3. Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Dashboard opens at `http://localhost:5173`.

---

## 📁 Project Structure

```
samvaad-1092/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI entry point
│   │   ├── config.py               # Pydantic settings
│   │   ├── models/
│   │   │   └── schemas.py          # Domain models (CallSession, VerificationState, etc.)
│   │   ├── core/
│   │   │   ├── acoustic_guardian.py # Distress detection (librosa)
│   │   │   ├── pii_scrubber.py     # PII redaction (regex + NER)
│   │   │   ├── llm_swarm.py        # SovereignProvider factory + cascade
│   │   │   └── verification_fsm.py # State machine engine
│   │   └── ws/
│   │       └── call_handler.py     # WebSocket connection manager
│   ├── requirements.txt
│   └── tests/
│       └── test_pii_scrubber.py
├── dashboard/
│   ├── src/
│   │   ├── App.jsx                 # Main dashboard layout
│   │   ├── index.css               # Glassmorphism design system
│   │   ├── hooks/
│   │   │   └── useCallSocket.js    # WebSocket hook
│   │   └── components/
│   │       ├── RadialGauge.jsx     # SVG gauge for distress/confidence
│   │       ├── StateTimeline.jsx   # FSM visualisation
│   │       ├── TranscriptPanel.jsx # Live transcript feed
│   │       ├── AnalysisCard.jsx    # LLM analysis display
│   │       └── SimulatorPanel.jsx  # Call simulation tool
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── .env.example
├── .gitignore
└── README.md
```

---

## 🔐 Security Posture

| Concern | Mitigation |
|---------|-----------|
| PII in LLM calls | Local scrubbing (regex + NER) before any API call |
| Audio data | Processed on-device by Acoustic Guardian; never transmitted |
| API keys | Environment variables, never in source control |
| WebSocket auth | CORS-restricted to dashboard origin |
| Sensitive transcripts | Stored in-memory only; no disk persistence in demo |

---

## 🏛 Government Feasibility

- **Language coverage:** Kannada, Hindi, English — with dialect-aware analysis
- **Latency:** Sub-second sentiment extraction via Groq LPU hardware
- **Reliability:** Cascade failover across 3 LLM providers
- **Privacy:** Zero PII exposure to cloud services
- **Auditability:** Full cascade log + state machine trace per call
- **Operator UX:** Low cognitive-load monochrome interface

---

## 📜 License

MIT License — Built with ❤️ for AI for Bharat 2.
