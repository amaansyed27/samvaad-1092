# Testing Guide: Samvaad 1092

This guide outlines the testing procedures for the **Samvaad 1092** platform, ensuring compliance with the hackathon's "Verified Understanding" and "Sovereign Privacy" mandates.

---

## 🛠️ Testing Environment Setup

Before testing, ensure your backend and dashboard are running:
- **Backend**: `uvicorn app.main:app --reload` (Port 8000)
- **Dashboard**: `npm run dev` (Port 5173)
- **Check**: Navigate to [http://localhost:5173](http://localhost:5173). You should see "Live" status in the top right.

---

## 🧪 Phase 1: Security & Sovereignty Testing (Local)

### 1.1 PII Redaction Verification
The goal is to ensure no citizen data (Aadhaar, Phone, Name) reaches the LLM swarm.
- **Action**: Use "Text Simulator" mode.
- **Test Input**: "Hello, my name is Amaan Syed and my phone number is 9876543210. My Aadhaar is 1234 5678 9101."
- **Expected Outcome**:
  - The "Live Transcript" shows the raw text.
  - The "State Timeline" advances to **SCRUB PII**.
  - In the backend logs or DB record, the `scrubbed_transcript` should show: "Hello, my name is [NAME_REDACTED] and my phone number is [PHONE_REDACTED]. My Aadhaar is [AADHAAR_REDACTED]."
  - **Verdict**: Pass if LLM analysis uses only the scrubbed text.

### 1.2 Acoustic Guardian (Distress Detection)
Ensures immediate escalation for life-threatening situations without ASR lag.
- **Action**: Switch to "Live Mic" mode.
- **Test Input**: Shouting or loud/high-pitch sounds (simulating panic).
- **Expected Outcome**:
  - The "Distress" gauge should spike into the **CRITICAL** (red) zone.
  - The state should instantly jump to **SAFE_HUMAN_TAKEOVER**.
  - **Verdict**: Pass if the system bypasses the verification loop for high-stress audio.

---

## 🌍 Phase 2: Multilingual & Dialect Testing

### 2.1 Kannada Dialect Analysis
- **Action**: Paste/Speak a Kannada transcript with regional dialect (e.g., North Karnataka variation).
- **Expected Outcome**:
  - `language_detected` identifies Kannada.
  - `AnalysisCard` shows `cultural_context` identifying the dialect/nuance.
  - `restated_summary` is generated in correct Kannada script.

### 2.2 Hindi/English Code-Mixing
- **Action**: Use mixed input: "Mujhe problem hai, station ke paas accident hua hai, help me fast."
- **Expected Outcome**:
  - AI identifies the emergency as "Accident".
  - Severity is set to "High" or "Critical".
  - Restatement captures the bilingual intent.

---

## 🤝 Phase 3: Human-in-the-Loop (HITL) Testing

### 3.1 Agent Corrections (Learning Signals)
- **Action**: Send a transcript. Once the **Analysis Card** appears, click "✏ Edit".
- **Change**: Alter the `Emergency Type` or `Severity`. Click "⬆ Save".
- **Expected Outcome**:
  - Dashboard shows "✓ Saved".
  - Check `http://localhost:8000/api/learning`. The new correction should appear in the learning signal list.
  - **Verdict**: Pass if agent corrections are persisted for model fine-tuning.

### 3.2 Manual Takeover
- **Action**: Click the "⚠ Manual Takeover" button during an active analysis.
- **Expected Outcome**:
  - State moves to `HUMAN_TAKEOVER`.
  - Backend persists the current session with the "Agent manual takeover" reason.

---

## ✅ Hackathon Compliance Checklist

| Criterion | Test Reference | Result |
|---|---|---|
| **Verified Understanding** | Confirm/Reject loop in Simulator | [ ] |
| **Multilingual Support** | Kannada/Hindi ASR + TTS tests | [ ] |
| **Acoustic Distress** | Mic recording vs Distress Gauge | [ ] |
| **PII Data Security** | Scrubbing logs check | [ ] |
| **Agent-in-the-Loop** | Analysis Card edit test | [ ] |
| **High Concurrency** | Multiple browser tabs connected | [ ] |

---

## 🐛 Troubleshooting
- **WebSocket Error**: Check if Vite proxy is active. Ensure `backend/app/main.py` is running on the correct port.
- **TTS No Sound**: Ensure your browser hasn't blocked "Autoplay with sound". Click the "🔊 Replay" button to test.
- **Empty Analysis**: Check your `.env` for valid OpenRouter or Gemini API keys.
