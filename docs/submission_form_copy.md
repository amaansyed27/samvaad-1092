# Samvaad 1092 Submission Form Copy

## Title

Samvaad 1092: Verified Multilingual Voice AI for Karnataka Public Grievance Intake

## Description

Samvaad 1092 is a voice-to-voice AI assistive layer for Karnataka-style public grievance calls. It helps citizens speak naturally in English, Kannada, Hindi, or code-mixed speech, then verifies the system's understanding before a ticket is registered or the call is handed to a human operator.

The prototype demonstrates a live call-center style flow: IVR language selection, Sarvam STT/TTS voice interaction, low-latency transcript updates, deterministic department routing, sentiment and distress detection, location/map-pin disambiguation, explicit confirmation, ticket logging, Civic Inbox history, and active-learning records from agent corrections.

The system is aligned with Theme 12: AI for 1092 Helpline. It is not just a chatbot; it is a first-level grievance intake assistant designed to reduce wrong routing caused by misunderstood language, dialect, location, urgency, or emotional context.

Technical stack:

- Backend: Python 3.12, FastAPI, WebSockets, Pydantic, async call-state management, SQLite through `aiosqlite`, and a deterministic verification finite-state machine.
- Frontend: React 19, Vite, Tailwind-style utility classes, Recharts, Lucide icons, and a real-time operator dashboard with Live Transcript, Analysis Card, Civic Inbox, analytics, and debug simulator.
- Voice AI: Sarvam AI is used as the India-first speech layer. Sarvam Saaras STT converts caller speech into English/Hindi/Kannada transcripts, and Sarvam Bulbul TTS speaks the assistant responses back in a lighter female voice. The prototype uses Sarvam for multilingual Indian speech because the problem specifically needs Indian languages, code-mix behavior, and local accent handling.
- Telephony: Twilio is used for the live phone-call simulation because Twilio provides free/trial phone numbers and programmable voice webhooks that are easy to connect during a hackathon. This simulates how a production deployment could connect to Exotel or a similar Indian telephony provider commonly used in government and enterprise call-center systems. The voice architecture is provider-agnostic: phone audio frames enter the FastAPI backend, are transcribed, analyzed, verified, and responded to through TTS.
- ML and AI layer: The project combines deterministic routing, local ML, and LLM enrichment. A fast local department classifier/predictor routes likely departments such as BESCOM, BBMP, BWSSB, Food/Civil Supplies, Labour, Health, Social Welfare, Transport/RTO, Revenue, Police, Women safety, Ambulance, and Fire. The deterministic verification FSM handles ticket readiness, slot completion, confirmation, repeated misunderstanding, spam/prank guardrails, and emergency referral without waiting on a heavy LLM every turn. LLMs are reserved for enrichment such as ambiguity, cultural context, sentiment, and complex phrasing.
- Active learning: Every verified interpretation, caller correction, agent edit, partial-correct response, incorrect response, and manual takeover can be saved as a learning signal. These records are stored with raw/scrubbed transcripts, extracted fields, department labels, priority, sentiment, and agent corrections so future versions of the classifier/predictor can be retrained on validated civic call data.
- Privacy and safety: PII scrubbing runs before external LLM enrichment. The system stores raw transcript, scrubbed transcript, full conversation turn log, structured memory, and ticket state locally. High distress, immediate danger, repeated misunderstanding, and low-confidence cases trigger human takeover rather than unsafe automation.

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

Deployment note:

The working prototype is run locally because it requires Sarvam/Twilio credentials. I was not able to deploy the full phone-call version during the prototype phase due to Twilio account/department limitations. If selected for the final round, I plan to show a scalable Google Cloud deployment with secure data handling: Cloud Run or GKE for the FastAPI backend, managed secrets for API keys, Cloud SQL/Firestore for structured grievance records, Cloud Storage for controlled artifacts, HTTPS WebSocket ingress, and audit-friendly IAM/network controls.

## Video URL

Paste your Loom/Drive/YouTube unlisted demo video link here.

Suggested video title: Samvaad 1092 Demo - Multilingual Voice AI for Verified Grievance Intake

## Demo Link

If not deployed, use the repository URL and clearly mention in the video that the working prototype is run locally because it requires Sarvam/Twilio credentials.

Recommended text if the form accepts notes:

Local prototype. Please use the repository and source-code upload to run. The demo video shows the working browser and Twilio call flows. The working prototype is run locally because it requires Sarvam/Twilio credentials. I was not able to deploy due to Twilio account/department limitations; if selected for the final round, I will show a scalable Google Cloud deployment with secure data handling.

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

Target pace: speak naturally, but keep the demos moving. If the screen is slow, skip one follow-up and show the dashboard result.

1. Opening, 25 seconds:
   - "Hello, I am Amaan Syed from RedLine, and this is Samvaad 1092."
   - "Samvaad is a voice-to-voice AI intake layer for Karnataka public grievance calls."
   - "The goal is not only verified understanding. It also reduces call-center load by automating first-level intake: listening, routing, collecting key details, verifying, and creating a ticket before a human operator is needed."

2. Problem and solution, 35 seconds:
   - "In grievance calls, the biggest failure is a wrong response caused by wrong understanding."
   - "Citizens may speak in Kannada, Hindi, English, code-mix, local landmarks, or emotional language."
   - "Samvaad listens, extracts the issue, department, location, urgency, and service details, then verifies everything aloud before registering the grievance."

3. Stack and guardrails, 45 seconds:
   - "The backend is FastAPI with WebSockets, SQLite, Pydantic models, and a deterministic verification state machine."
   - "The dashboard is React and Vite, showing the live transcript, classification, priority, slots, Civic Inbox, and learning signals."
   - "Sarvam handles Indian-language speech-to-text and text-to-speech. Twilio is used for the phone demo because it gives trial numbers; in production this can map to Exotel or a government telephony provider."
   - "The ML layer includes department classification, priority prediction from the caller's actual impact, distress detection, active learning from agent corrections, and spam or prank-call detection. Fake, abusive, or dummy calls can be warned, blocked, or routed to a human instead of wasting operator time."

4. Demo setup, 10 seconds:
   - "Now I will switch to the dashboard and phone window. I will show four fast calls: power cuts, ration card delay, streetlight safety, and contaminated water."

5. Demo 1: Power cuts, 55 seconds:
   - Say: "I am facing too many electrical cuts at my house near Esplanade Apartments on 100 Feet Road, Indiranagar."
   - If asked: "It has been happening for two weeks. In the last three days we had seven cuts, and one lasted over three hours."
   - Point out: "It routes to BESCOM, raises priority because the outage is repeated and long, cleans the location, verifies, and creates a ticket."

6. Demo 2: Ration card, 45 seconds:
   - Say: "My ration card application is pending for two months in Mysuru."
   - If asked: "It is linked with the same mobile number."
   - Point out: "This is no longer just BBMP or BESCOM. It routes to Food and Civil Supplies, captures Janaspandana-style service fields, and verifies before logging."

7. Demo 3: Streetlight safety, 50 seconds:
   - Say: "There are no street lights on the road from the metro to my house. I walk there at night and I do not feel safe."
   - If asked: "It is from Indiranagar metro station towards 5th Cross, near Esplanade Apartments."
   - Point out: "The system treats this as streetlights plus safety context, asks for exact route or landmark, and escalates priority instead of treating it as a routine road issue."

8. Demo 4: Contaminated water and child health, 45 seconds:
   - Say: "Water is contaminated near Whitefield and my child is sick after drinking it."
   - If asked: "It is near Vydehi Hospital, Whitefield."
   - Point out: "It routes BWSSB as primary, marks Health as a secondary concern, raises urgency, and can trigger operator attention."

9. Civic Inbox and learning, 25 seconds:
   - "Every verified call is saved with the full transcript, structured fields, ticket number, and active-learning signal."
   - "If an agent corrects a department, location, priority, or category, that becomes training data for future improvement."

10. Closing, 25 seconds:
   - "So Samvaad improves language access, reduces routine call-center workload, prevents wrong routing, detects unsafe or fake calls, and hands over to humans when needed."
   - "This prototype runs locally because Sarvam and Twilio credentials are required. If selected, I will deploy it on Google Cloud with secure secrets, storage, and scalable call processing."

## 90-Second Emergency Backup Video Script

Use this if time is very tight:

1. "Samvaad 1092 is a multilingual voice AI intake layer for Karnataka public grievances."
2. "It uses Sarvam for Indian-language speech, Twilio as a phone-call simulation, FastAPI for real-time call processing, React for the operator dashboard, and local ML/deterministic guardrails for routing and verification."
3. "Here is a power-cut call. Notice the transcript, BESCOM routing, priority, location, and confirmation."
4. "Here is a ration-card call. Notice it routes beyond civic departments into Food and Civil Supplies and captures a Janaspandana-style reference."
5. "Here is a streetlight safety call. Notice the system understands safety context and asks for exact route/location."
6. "Here is contaminated water with a sick child. It creates BWSSB as primary department and Health as secondary concern."
7. "The Civic Inbox stores transcript, extracted memory, ticket, and learning signals for future classifier improvement."
8. "The prototype runs locally because Sarvam/Twilio credentials are required. If selected, I will deploy it securely on Google Cloud."
