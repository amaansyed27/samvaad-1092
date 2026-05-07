# Tech Stack: Samvaad 1092

The platform is divided into a high-concurrency Python backend, a powerful Machine Learning layer, and a lightweight, reactive JavaScript frontend.

## Backend (Server & API)
- **Runtime**: Python 3.12
- **Framework**: FastAPI (Async, WebSockets)
- **Server**: Uvicorn
- **Database**: SQLite (Async via `aiosqlite` and `SQLAlchemy`)
- **Telephony Integration**: Twilio (WebSocket Media Streams)
- **Configuration**: Pydantic Settings

## Machine Learning & AI
- **Speech-to-Text (STT)**: Sarvam AI Saaras V3 (Auto-detects Kannada, Hindi, English).
- **Text-to-Speech (TTS)**: Sarvam AI Bulbul V3 (30+ Indian voices).
- **Fast Local ML Routing**: `scikit-learn`, `joblib` (TF-IDF + Naive Bayes / Random Forest models)
- **LLM Routing / Swarm**:
  - OpenRouter API (Primary reasoning: `nvidia/nemotron-3-super-120b`, `deepseek/deepseek-v4-flash`)
  - Groq API (Low-latency LLaMA 3 for sentiment analysis)
  - Google Gemini API (Multimodal/Reasoning fallback)
- **Audio Processing**: `librosa`, `soundfile` (for Acoustic Guardian distress detection).
- **PII Redaction**: Built-in Regex rules + Extensible hooks for IndicNER (`transformers`, `torch`).
- **Location Search**: Dynamic geocoder provider chain using OpenStreetMap Nominatim by default, with a local fallback for offline demos.

## Frontend (Operator Dashboard)
- **Framework**: React 18
- **Build Tool**: Vite
- **Styling**: Tailwind CSS (Custom minimalist, monochrome glassmorphism "Paper" theme)
- **Data Visualization**: `recharts` (Bar charts, Pie charts for Analytics)
- **Icons**: `lucide-react`
- **State Management**: React Hooks (`useState`, `useRef`, `useCallback`)
- **Real-Time Comm**: Native Browser `WebSocket` API

## Development & Operations
- **Version Control**: Git
- **Dependency Management**: `pip` (Backend), `npm` (Frontend)
- **Environment Management**: `.env` (python-dotenv)
- **Tunneling (For Twilio)**: `ngrok` / `localtunnel`

## Current Voice Runtime Details
- **IVR / Language Lock**: Twilio TwiML gathers `1`, `2`, or `3` and passes `en-IN`, `kn-IN`, or `hi-IN` into the media stream.
- **STT Path**: Sarvam streaming STT is attempted first; buffered WAV is sent through Sarvam REST STT when streaming does not emit a final transcript.
- **TTS Path**: Sarvam Bulbul v3 uses a light female voice configuration and streams audio chunks back to browser/Twilio.
- **Turn-Taking**: Twilio VAD uses RMS thresholds and assistant-echo protection. Barge-in is explicit and does not cancel playback on every inbound frame.
- **Dashboard Diagnostics**: WebSocket events expose audio activity, STT fallback state, latency metrics, slot updates, conversation memory, and transcript turns.
- **Location Verification**: Heard landmarks are searched through the geocoder, candidate confidence is shown to the operator, and browser geolocation can send a precise map pin through the `location_pin` WebSocket event.
