# Samvaad 1092 📞

**AI for Karnataka 1092 Helpline (Theme 12)**

Samvaad 1092 is a production-grade, voice-to-voice AI assistive layer built for the Karnataka 1092 Civic Grievance Helpline. It focuses heavily on **Verified Administrative Understanding** — ensuring that a citizen's issue, local dialect, and cultural context are precisely understood and routed to the correct administrative department (e.g., BESCOM, BBMP, BWSSB) before a human operator takes action.

It utilizes a Sovereign Hybrid Architecture, blending fast local Machine Learning (Scikit-Learn Naive Bayes department routing, Acoustic Distress analysis, local PII scrubbing) with powerful Swarm LLM Intelligence and Sarvam AI's speech bridge (Saaras V3 STT & Bulbul V3 TTS).

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
python -m app.main
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

---

## 🛡️ Security Note

Samvaad 1092 implements rigorous, on-device PII scrubbing (Regex + IndicNER) **before** any transcript is sent to external LLMs. Raw audio is processed through Sarvam AI (Indian DPI) and is never sent to US-based LLM providers. All "Learning Signals" (verified logs and agent edits) are saved locally to an asynchronous SQLite database.
