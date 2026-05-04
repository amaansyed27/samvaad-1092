# Samvaad 1092 📞

**AI for Karnataka 1092 Helpline (Theme 12)**

Samvaad 1092 is a production-grade, voice-to-voice AI assistive layer built for high-stress government emergency helplines. It enforces a strict **Verified Understanding** pipeline, ensuring that a caller's emergency, language, and cultural context are fully understood by the AI and verified by the caller before a human operator dispatches resources.

It utilizes a Sovereign Hybrid Architecture, blending localized PII scrubbing and Acoustic Distress analysis with powerful Swarm LLM Intelligence and Sarvam AI's speech bridge (Saaras V3 STT & Bulbul V3 TTS).

---

## 📖 Documentation

Detailed documentation has been separated into the following modules to help you understand the architecture, working, tech stack, and theory behind Samvaad 1092:

- [**Architecture**](docs/architecture.md): High-level system architecture, FSM, and Swarm Intelligence.
- [**Working Mechanism**](docs/working.md): Step-by-step pipeline from voice input to database persistence.
- [**Tech Stack**](docs/tech_stack.md): Detailed breakdown of the frameworks, APIs, and models used.
- [**Theory & Philosophy**](docs/theory.md): The core design philosophies (Sovereign Privacy, Acoustic Superiority, Agent-in-the-Loop).
- [**Testing Guide**](docs/testing_guide.md): Step-by-step scenarios to verify hackathon requirements.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+
- Node.js 18+
- API Keys: Sarvam AI, OpenRouter, Groq, Gemini (optional DeepSeek)

### 2. Backend Setup
```bash
cd backend
python -m venv .venv
# Activate virtual environment
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate

pip install -r requirements.txt

# Copy config and add your keys
cp ../.env.example ../.env

# Start the FastAPI server (starts on port 8000)
uvicorn app.main:app --reload
```

### 3. Dashboard Setup
```bash
cd dashboard
npm install

# Start the Vite dev server (starts on port 5173)
npm run dev
```

### 4. Usage
Open [http://localhost:5173](http://localhost:5173) in your browser.
- **Microphone Mode**: Click "Live Mic", speak into your microphone (in English, Hindi, or Kannada), and watch the pipeline process your voice.
- **Text Mode**: Use the text simulator to paste a transcript directly.
- **Agent Action**: You can edit the AI's classification in real-time or click "Manual Takeover" to escalate.

---

## 🛡️ Security Note

Samvaad 1092 implements rigorous, on-device PII scrubbing (Regex + IndicNER) **before** any transcript is sent to external LLMs. Raw audio is processed through Sarvam AI (Indian DPI) and is never sent to US-based LLM providers. All "Learning Signals" (verified logs and agent edits) are saved locally to an asynchronous SQLite database.
