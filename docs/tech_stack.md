# Tech Stack: Samvaad 1092

The platform is divided into a high-concurrency Python backend and a lightweight, reactive JavaScript frontend.

## Backend (Server & Intelligence)
- **Runtime**: Python 3.12
- **Framework**: FastAPI (Async, WebSockets)
- **Server**: Uvicorn
- **Database**: SQLite (Async via `aiosqlite` and `SQLAlchemy`)
- **Configuration**: Pydantic Settings

### AI & Machine Learning Integrations
- **Speech-to-Text (STT)**: Sarvam AI Saaras V3 (Auto-detects Kannada, Hindi, English).
- **Text-to-Speech (TTS)**: Sarvam AI Bulbul V3 (30+ Indian voices).
- **LLM Routing / Swarm**:
  - OpenRouter API (Primary reasoning: `nvidia/nemotron-3-super-120b`, `deepseek/deepseek-v4-flash`)
  - Groq API (Low-latency LLaMA 3 for sentiment analysis)
  - Google Gemini API (Multimodal/Reasoning fallback)
- **Audio Processing**: `librosa`, `soundfile` (for Acoustic Guardian distress detection).
- **PII Redaction**: Built-in Regex rules + Extensible hooks for IndicNER.

## Frontend (Operator Dashboard)
- **Framework**: React 18
- **Build Tool**: Vite
- **Styling**: Tailwind CSS (Custom minimalist, monochrome glassmorphism "Paper" theme)
- **State Management**: React Hooks (`useState`, `useRef`, `useCallback`)
- **Real-Time Comm**: Native Browser `WebSocket` API
- **Audio Capture**: Native Browser `MediaRecorder` API
- **Audio Playback**: Native Browser `AudioContext` & `HTMLAudioElement`

## Development & Operations
- **Version Control**: Git
- **Dependency Management**: `pip` (Backend), `npm` (Frontend)
- **Environment Management**: `.env` (python-dotenv)
