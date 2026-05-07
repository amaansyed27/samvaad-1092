# Samvaad 1092 Submission Form Copy

## Title

Samvaad 1092: Verified Multilingual Voice AI for Karnataka Public Grievance Intake

## Description

Samvaad 1092 is a voice-to-voice AI assistive layer for Karnataka-style public grievance calls. It helps citizens speak naturally in English, Kannada, Hindi, or code-mixed speech, then verifies the system's understanding before a ticket is registered or the call is handed to a human operator.

The prototype demonstrates a live call-center style flow: IVR language selection, Sarvam STT/TTS voice interaction, low-latency transcript updates, deterministic department routing, sentiment and distress detection, location/map-pin disambiguation, explicit confirmation, ticket logging, Civic Inbox history, and active-learning records from agent corrections.

The system is aligned with Theme 12: AI for 1092 Helpline. It is not just a chatbot; it is a first-level grievance intake assistant designed to reduce wrong routing caused by misunderstood language, dialect, location, urgency, or emotional context.

Key capabilities:

- Voice-to-voice interaction in English, Kannada, and Hindi.
- Public grievance intake across BESCOM, BBMP, BWSSB, Food/Civil Supplies, Labour, Health, Social Welfare, Transport/RTO, Education, Revenue, RDPR, Municipality/Panchayat, Police, Women safety, Ambulance, and Fire.
- Janaspandana/iPGRS-style fields: request type, line department, service/scheme, application/reference number, office visited, documents/photo availability, location, and status lookup.
- Confirmation loop before ticket registration.
- Human takeover for immediate danger, repeated misunderstanding, high distress, or emergency referral.
- Dynamic location verification with geocoder candidates, map pin support, and broad/fake-location guardrails.
- Full conversation transcript and extracted memory stored in Civic Inbox.
- Active learning through verified tickets and agent corrections.

Demo highlights:

- Power-cut complaint routes to BESCOM and captures repeated outage impact.
- Ration card delay routes to Food and Civil Supplies and accepts mobile number as reference.
- Streetlight plus women-safety context raises priority and asks for exact route/location.
- Immediate safety issue triggers human/operator handoff instead of form-filling.
- Contaminated water plus sick child creates BWSSB grievance with Health cross-department note.

## Video URL

Paste your Loom/Drive/YouTube unlisted demo video link here.

Suggested video title: Samvaad 1092 Demo - Multilingual Voice AI for Verified Grievance Intake

## Demo Link

If not deployed, use the repository URL and clearly mention in the video that the working prototype is run locally because it requires Sarvam/Twilio credentials.

Recommended text if the form accepts notes:

Local prototype. Please use the repository and source-code upload to run. The demo video shows the working browser and Twilio call flows.

## Repository URL

Paste your GitHub repository URL here.

## Instructions to Run

Prerequisites:
- Python 3.12+
- Node.js 18+
- Sarvam AI API key
- Optional: Twilio account and ngrok for phone-call demo

Steps:

1. Clone the repository.
2. Copy `.env.example` to `.env` at the project root.
3. Add required API keys in `.env`, especially Sarvam credentials.
4. Start the backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/demo_data_seeder.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. Start the dashboard in a second terminal:

```bash
cd dashboard
npm install
npm run dev
```

6. Open `http://localhost:5173`.
7. Use the Live Call debug simulator from the dashboard sidebar, select language, and speak/read a test scenario from `docs/demo_test_scenarios.md`.
8. For Twilio phone testing, expose backend port 8000 through ngrok and configure the Twilio webhook to the backend voice endpoint as described in the README.

Expected result:
- Live transcript appears.
- Assistant asks one question at a time.
- Department, line department, sentiment, priority, location, and slots update on the dashboard.
- Confirmed calls generate a ticket ID and appear in Civic Inbox with full conversation history.

## Custom Attachment Suggestions

Upload one of these:

- `Samvaad-1092-Redline.pdf`
- Demo transcript and call audio recording
- Screenshots collage PDF
- Architecture/working notes from `docs/`

## Screenshots to Upload

Use PNG/JPG under 3 MB each:

1. Live call dashboard showing transcript, classification, slots, and assistant response.
2. Civic Inbox detailed view showing full conversation and extracted memory.
3. Analysis card showing request type, line department, priority, sentiment, helpline/referral, and location validation.

## 5-Minute Video Script

1. Opening, 20 seconds:
   - "This is Samvaad 1092, a voice-to-voice AI assistive layer for Karnataka public grievance calls."
   - "The core problem is wrong understanding before response."

2. Architecture, 40 seconds:
   - Browser/Twilio audio goes to FastAPI.
   - Sarvam handles STT/TTS.
   - Local PII scrubbing, acoustic distress, deterministic routing, and verification happen before ticketing.
   - Dashboard gives human-in-the-loop control.

3. Demo 1, 90 seconds:
   - Power cut or ration card case.
   - Show transcript, routing, slots, confirmation, ticket.

4. Demo 2, 60 seconds:
   - Streetlight/women-safety or immediate danger case.
   - Show priority, empathy, and human takeover/referral.

5. Civic Inbox, 45 seconds:
   - Show stored conversation, extracted fields, learning signal.

6. Closing, 30 seconds:
   - "This improves language access, verified understanding, safe escalation, and government deployability."

