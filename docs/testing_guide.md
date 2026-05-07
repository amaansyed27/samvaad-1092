# Testing Guide: Samvaad 1092

This guide outlines the testing procedures for the **Samvaad 1092** platform, ensuring compliance with the hackathon's "Verified Understanding" and "Sovereign Privacy" mandates.

---

## 🛠️ Testing Environment Setup

Before testing, ensure your backend and dashboard are running:
- **Backend**: `uvicorn app.main:app --reload` (Runs on Port 8000)
- **Dashboard**: `npm run dev` (Runs on Port 5173)

### Option A: The "Live Phone" Demo (Twilio + Ngrok) - Recommended
To show a real-world, production-ready system:
1. Run ngrok to expose your local backend: `ngrok http 8000` (or use `lt --port 8000`).
2. Copy the forwarding URL (e.g. `https://xxxx-xxxx.ngrok-free.dev`).
3. In your Twilio Console, go to your Active Phone Number -> Voice Configuration.
4. Set "A CALL COMES IN" to Webhook, and paste: `https://[your-ngrok-url]/api/twiml`.
5. Open your Dashboard at `http://localhost:5173` and stay on the "Overview" or "Inbox" tab.
6. Call the Twilio phone number from your mobile device. The Dashboard will automatically detect the call and snap to the Live Terminal view!

### Option B: The "Browser Mic" Debug Mode
If you don't have cellular service or Twilio:
1. Open the Dashboard at `http://localhost:5173`.
2. Click the **"Bug / Debug"** icon in the bottom-left of the sidebar to reveal the Call Simulator Panel.
3. Use the **Text Mode** to paste transcripts, or the **Live Mic** button to speak into your laptop microphone.

---

## 🧪 Phase 1: Security & ML Routing Testing

### 1.1 Local ML Department Routing
- **Action**: Call the number or use the simulator. Say: "There is a massive pothole in front of my house."
- **Expected Outcome**: The dashboard instantly flashes a **"⚡ Fast ML Routed"** badge with high confidence, routing it to `BBMP`.

### 1.2 PII Redaction Verification
The goal is to ensure no citizen data reaches the LLM swarm.
- **Action**: Use "Text Simulator" mode.
- **Test Input**: "My phone number is 9876543210 and my Aadhaar is 1234 5678 9101."
- **Expected Outcome**: The database log shows `scrubbed_transcript`: "My phone number is [PHONE_REDACTED] and my Aadhaar is [AADHAAR_REDACTED]."

---

## 🌍 Phase 2: Multilingual & Dialect Testing

### 2.1 Code-Mixed Speech Processing
- **Action**: Use mixed input: "Road damage hai sir, please help me fast."
- **Expected Outcome**:
  - `language_detected` identifies Hindi/English mix.
  - The AI identifies the grievance as "Road Damage" and routes it to `BBMP`.
  - Restatement is generated in Hindi/English.

---

## 🤝 Phase 3: Human-in-the-Loop (HITL) Testing

### 3.1 Agent Corrections (Learning Signals)
- **Action**: Call the system. Once the **Analysis Card** appears, click "✏ Edit".
- **Change**: Alter the `Department` from `UNASSIGNED` to `POLICE`. Click "⬆ Save".
- **Expected Outcome**:
  - The dashboard updates immediately.
  - The edit is committed to the SQLite `call_records` table under `agent_corrections`. This data serves as the foundation for retraining the local ML classifier.

### 3.2 Grievance Resolution
- **Action**: Navigate to the "Inbox" tab on the dashboard.
- **Change**: Find a "PENDING" grievance and click "Mark Resolved".
- **Expected Outcome**: The ticket turns green, and the "Analytics Overview" tab instantly updates the resolution rate chart.

---

## ✅ Hackathon Compliance Checklist

| Criterion | Test Reference | Result |
|---|---|---|
| **Voice-to-Voice Primary Focus** | Real Twilio cell phone test | [ ] |
| **Verified Understanding** | AI restates the issue and waits for confirmation | [ ] |
| **Dialect/Cultural Context** | LLM extracts specific location/cultural hints | [ ] |
| **Learning from Feedback** | Agent Edits are saved to SQLite DB | [ ] |
| **Scalability (Tech Design)** | Fast Local ML routing before heavy LLM processing | [ ] |

---

## Current Demo Acceptance Tests

### Conversational Power-Cut Intake
- Select English.
- Say: "I am facing too many electrical cuts at my house."
- Expected:
  - Transcript appears as `FINAL`.
  - Department becomes `BESCOM`.
  - Required slot becomes `landmark`.
  - Assistant says it understands the problem and asks for area/nearest landmark.

### Location and Optional Detail
- Say: "Whitefield near Vydehi hospital."
- Expected:
  - `ticket_ready=true`.
  - Assistant asks at most one optional operational question, such as when the issue started.
- Say: "Just create ticket."
- Expected:
  - Optional questions stop.
  - Assistant reads back the issue/location/department and asks for confirmation.

### Twilio Audio Debugging
During a live phone call, verify that the Live Transcript shows:
- `AUDIO: speech_started` when the caller speaks.
- `STT: audio_end_received` after the utterance.
- `STT: transcript_ready` before `FINAL`.

If `STT: empty_transcript` appears, audio reached the backend but Sarvam returned no text. If no `AUDIO:*` event appears, Twilio audio is not reaching the backend.

### Language Lock
- Press `1`: assistant continues in English.
- Press `2`: assistant acknowledges in Kannada and uses `kn-IN` for Sarvam TTS/STT.
- Press `3`: assistant acknowledges in Hindi and uses `hi-IN` for Sarvam TTS/STT.
