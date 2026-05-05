# Working Mechanism: Samvaad 1092

This document details the step-by-step flow of a single emergency call within the Samvaad 1092 platform.

## The Voice-to-Voice Pipeline

### Step 1: Telephony Ingestion & Acoustic Analysis
1. A citizen dials the 1092 Twilio phone number.
2. Twilio streams raw 8kHz µ-law audio over a WebSocket to the FastAPI backend. (For debug mode, the browser's `MediaRecorder API` captures audio).
3. **Voice Activity Detection (VAD)**: The backend buffers incoming audio based on volume energy (RMS). It waits for the user to finish speaking (a 0.5s pause) before processing, preventing tiny chunks of background noise from causing AI hallucinations.
4. **Parallel Processing**:
   - The audio chunk is immediately sent to the **Acoustic Guardian**. Using a custom trained Random Forest model, it analyzes acoustic features (Pitch, MFCC, ZCR) to calculate an "Acoustic Distress Score".

### Step 2: Speech-to-Text (STT) & ML Routing
1. The audio is forwarded to the **Sarvam AI Saaras V3** STT engine.
2. The model auto-detects the spoken language (Kannada, Hindi, English, or Code-mixed) and returns a raw transcript.
3. The raw transcript is passed into a **Local Scikit-Learn Classifier** (Naive Bayes). This model predicts the government department (e.g., BESCOM, BBMP, Police) in under 5 milliseconds. 
4. The raw transcript and ML department prediction are streamed back to the Operator Dashboard in real-time.

### Step 3: Data Sanitization (PII Scrubbing)
1. The raw transcript enters the **PII Scrubber**.
2. Regular expressions target structured data (Aadhaar, PAN, Phone Numbers).
3. Local NLP models (IndicNER) identify and redact unstructured names and addresses.
4. Output: A clean, anonymized transcript (e.g., "My name is [NAME_REDACTED] and I have no water at [LOCATION_REDACTED]").

### Step 4: Swarm Analysis (LLMs)
1. The scrubbed text and the Acoustic Distress score are sent to the **LLM Swarm Cascade**.
2. **Sentiment Analysis**: A fast, low-latency model (e.g., Groq) analyzes the emotional tone (distressed, calm, angry).
3. **Civic Classification**: A heavy reasoning model (e.g., DeepSeek/Nemotron) parses the text to determine the specific grievance type, severity, location hints, and cultural context/dialect. If the ML routed department was incorrect or "UNKNOWN", the LLM updates it.
4. The dashboard updates with the generated `AnalysisCard`.

### Step 5: Verification & Restatement
1. The LLM generates a short, precise restatement in the caller's native language (e.g., "You are reporting a power cut in Koramangala. Is that correct?").
2. This text is sent to the **Sarvam AI Bulbul V3** Text-to-Speech (TTS) engine.
3. The resulting Base64 WAV audio is encoded back to 8kHz µ-law and sent over the WebSocket to Twilio, which plays it to the caller.

### Step 6: Confirmation & Learning
1. The caller confirms (Yes/No).
2. If confirmed, the call state becomes `VERIFIED`. The AI plays a final dispatch message ("Help is on the way").
3. **Agent-in-the-Loop**: The human operator can manually edit the AI's classification on the dashboard.
4. The final verified data, along with any agent corrections, is saved to the **SQLite database**. These are "Learning Signals" used to actively retrain the Local ML Department Classifier.
