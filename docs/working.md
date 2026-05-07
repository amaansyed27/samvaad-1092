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

---

## Current Conversational Intake Flow

The current live call path is optimized for first-level grievance intake:

1. The caller selects language through IVR: English, Kannada, or Hindi.
2. The language choice locks STT/TTS for the rest of the call.
3. The assistant acknowledges the issue before asking for details.
4. Required fields are collected first: issue, department, and usable location.
5. Location is validated through the dynamic location resolver. Heard landmarks are searched through the configured geocoder, map candidates are shown on the dashboard, and weak matches trigger a caller confirmation or operator map pin.
6. Optional details are asked only when useful: time, frequency, whether the issue is happening now, what the caller already tried, authority contact, and prior complaint number.
7. If the caller says "just create ticket" or sounds urgent/frustrated, optional questions are skipped and the assistant verifies immediately.
8. Confirmed calls persist the full turn log and structured memory to the Civic Inbox.

## Dynamic Location Resolver

The resolver is deliberately provider-neutral:

1. Search the configured dynamic geocoder (`LOCATION_GEOCODER_PROVIDER=nominatim` by default).
2. Use browser/operator map pin data when the caller shares location from the dashboard debug mode.
3. Fall back to the local demo gazetteer only if the geocoder is disabled or unavailable.

The FSM stores `map_candidates`, `geo_pin`, `location_source`, `location_confirmed`, and `location_validation_status` in conversation memory. If STT hears a difficult landmark such as "Espelad", the system can surface likely candidates and ask: "I heard the location as Esplanade Apartments. Is that correct?" This prevents silent dispatch to a wrong location.

## Audio and STT Diagnostics

The Live Transcript panel shows audio transport diagnostics:

- `AUDIO: speech_started`: Twilio VAD detected caller speech.
- `AUDIO: speech_ended`: Twilio decided the utterance ended.
- `STT: audio_end_received`: backend received an utterance boundary and has buffered audio.
- `STT: rest_fallback_started`: streaming STT did not produce a final transcript, so buffered audio is sent through Sarvam REST STT.
- `STT: transcript_ready`: STT produced usable text.
- `STT: empty_transcript` / `rest_timeout`: audio arrived but STT failed to produce text.

Barge-in is protected against echo: Twilio frames only cancel assistant playback when they are marked as real caller speech, not merely background audio.
