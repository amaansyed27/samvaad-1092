# Working Mechanism: Samvaad 1092

This document details the step-by-step flow of a single emergency call within the Samvaad 1092 platform.

## The Voice-to-Voice Pipeline

### Step 1: Ingestion & Acoustic Analysis
1. A citizen speaks into the phone/microphone.
2. The browser's `MediaRecorder API` captures audio in chunks (e.g., every 3 seconds) and sends it as Base64 encoded JSON over a WebSocket connection to the FastAPI backend.
3. **Parallel Processing**:
   - The audio chunk is immediately sent to the **Acoustic Guardian**. Using `librosa` and `Wav2Vec2`, it analyzes pitch variance, voice energy, and speaking rate to calculate a "Distress Score".
   - If the distress score exceeds the critical threshold (e.g., 0.85), the system immediately jumps to **Manual Takeover**, alerting a human agent.

### Step 2: Speech-to-Text (STT)
1. If the audio is not critically distressed, it is forwarded to the **Sarvam AI Saaras V3** STT engine.
2. The model auto-detects the spoken language (Kannada, Hindi, English, or Code-mixed) and returns a raw transcript.
3. The raw transcript is streamed back to the Operator Dashboard in real-time.

### Step 3: Data Sanitization (PII Scrubbing)
1. The raw transcript enters the **PII Scrubber**.
2. Regular expressions target structured data (Aadhaar, PAN, Phone Numbers).
3. Local NLP models (IndicNER) identify and redact unstructured names and addresses.
4. Output: A clean, anonymized transcript (e.g., "My name is [NAME_REDACTED] and I need an ambulance at [LOCATION_REDACTED]").

### Step 4: Swarm Analysis (LLMs)
1. The scrubbed text is sent to the **LLM Swarm Cascade**.
2. **Sentiment Analysis**: A fast, low-latency model (e.g., Groq) analyzes the emotional tone (panicked, calm, angry).
3. **Emergency Classification**: A heavy reasoning model (e.g., Nemotron 120B via OpenRouter) parses the text to determine the emergency type, severity, location hints, and cultural context.
4. The dashboard updates with the generated `AnalysisCard`.

### Step 5: Verification & Restatement
1. The LLM generates a short, empathetic restatement in the caller's native language (e.g., "I understand you need a fire engine in Koramangala. Is that correct?").
2. This text is sent to the **Sarvam AI Bulbul V3** Text-to-Speech (TTS) engine.
3. The resulting Base64 WAV audio is sent over the WebSocket to the browser, where it auto-plays to the caller.

### Step 6: Confirmation & Learning
1. The caller confirms (Yes/No) via voice or input.
2. If confirmed, the call state becomes `VERIFIED`.
3. **Agent-in-the-Loop**: The human operator can manually edit the LLM's classification on the dashboard.
4. The final verified data, along with any agent corrections, is saved to the **SQLite database** as a "Learning Signal" for future model training.
