# Samvaad 1092 📞

**AI for Karnataka 1092 Helpline (Theme 12)**

Samvaad 1092 is a production-grade, voice-to-voice AI assistive layer built for the Karnataka 1092 Civic Grievance Helpline. It focuses heavily on **Verified Administrative Understanding** — ensuring that a citizen's issue, local dialect, and cultural context are precisely understood and routed to the correct administrative department (e.g., BESCOM, BBMP, BWSSB) before a human operator takes action.

It utilizes a Sovereign Hybrid Architecture, blending fast local Machine Learning (Scikit-Learn Naive Bayes department routing, Acoustic Distress analysis, local PII scrubbing) with powerful Swarm LLM Intelligence and Sarvam AI's speech bridge (Saaras V3 STT & Bulbul V3 TTS).

Current live-demo capabilities:
- IVR language lock for English, Kannada, and Hindi.
- Sarvam STT/TTS voice-to-voice loop with REST STT fallback diagnostics.
- Conversational call-center intake that acknowledges the caller, asks one question at a time, verifies understanding, and logs a ticket.
- Deterministic guardrails for common civic categories such as BESCOM power-cut complaints.
- Dynamic location disambiguation with map/geocoder candidates, browser map-pin verification, and offline fallback.
- Full raw/scrubbed transcript, caller/assistant turn log, extracted intake memory, and learning signals in SQLite.
- Twilio barge-in handling with echo protection so assistant speech is not cancelled by line noise.

---

## 📖 Documentation

Detailed documentation has been separated into the following modules:

- [**Architecture**](docs/architecture.md): High-level system architecture, FSM, and Swarm Intelligence.
- [**Working Mechanism**](docs/working.md): Step-by-step pipeline from voice input to database persistence.
- [**Tech Stack**](docs/tech_stack.md): Detailed breakdown of the frameworks, APIs, and models used.
- [**Machine Learning & AI**](docs/ml_models.md): Deep dive into the Active Learning loop, the Scikit-Learn routing, and the Acoustic Guardian.
- [**Theory & Philosophy**](docs/theory.md): The core design philosophies (Sovereign Privacy, Acoustic Superiority, Agent-in-the-Loop).
- [**Testing Guide**](docs/testing_guide.md): Step-by-step scenarios to verify hackathon requirements.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+
- Node.js 18+
- API Keys: Sarvam AI, OpenRouter, Groq, Gemini (optional DeepSeek)
- (Optional) Twilio Account and ngrok for live phone network integration

### 2. Backend Setup
```bash
cd backend
python -m venv .venv
# Activate virtual environment
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate

pip install -r requirements.txt

# Seed the database with historical grievances for the dashboard
# (Uses robust synthetic data with noise and correlations)
python scripts/demo_data_seeder.py

# Start the FastAPI server (starts on port 8000)
uvicorn app.main:app --reload
```

### 3. Dashboard Setup
```bash
cd dashboard
npm install

# Start the Vite dev server
npm run dev
```

### 4. Usage
Open [http://localhost:5173](http://localhost:5173) in your browser.
You will see the **Civic Grievance Management System (CGMS)**.
- **Analytics Overview**: Real-time resolution metrics and department breakdowns.
- **Civic Inbox**: Searchable database of all historical and active calls.
- **Live Call (Terminal)**: To test live functionality, either:
  1. Click the "Bug / Debug" icon in the bottom left of the sidebar to open the web simulator.
  2. Or, set up Twilio + ngrok (port 8000) to call the system directly from your real mobile phone. The dashboard will automatically switch to Live Terminal mode when it detects an incoming call.

### Live Call Diagnostics
The Live Transcript panel includes transport-level debug events:
- `AUDIO: speech_started` / `speech_ended`: Twilio VAD saw caller speech.
- `STT: audio_end_received`: backend received an utterance boundary.
- `STT: rest_fallback_started`: buffered audio was sent through Sarvam REST STT.
- `STT: transcript_ready`: a usable transcript was produced.
- `STT: empty_transcript` or `rest_timeout`: audio arrived but STT could not produce text.

For phone demos, run ngrok against the same backend port used by the dashboard proxy, normally `8000`.

### Dynamic Location Verification
Location is not trusted only because STT heard a landmark. The backend first searches a dynamic geocoder (`LOCATION_GEOCODER_PROVIDER=nominatim` by default), then falls back to a small local demo gazetteer only if the provider is disabled or unavailable. If a heard landmark is ambiguous or likely misread, the assistant asks the caller to confirm the candidate or the operator can press **Send Pin** in debug mode to attach a browser map pin.

Useful config:
```env
LOCATION_GEOCODER_PROVIDER=nominatim
LOCATION_GEOCODER_TIMEOUT_SECONDS=0.65
LOCATION_GEOCODER_USER_AGENT=Samvaad1092-Hackathon/0.2
```

---

## 🛡️ Security Note

Samvaad 1092 implements rigorous, on-device PII scrubbing (Regex + IndicNER) **before** any transcript is sent to external LLMs. Raw audio is processed through Sarvam AI (Indian DPI) and is never sent to US-based LLM providers. All "Learning Signals" (verified logs and agent edits) are saved locally to an asynchronous SQLite database.
