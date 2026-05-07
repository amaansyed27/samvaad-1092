# Samvaad 1092 Demo Test Scenarios

Use this before the Twilio test. Start with the browser debug path at `http://localhost:5173`, select the language, and watch the Live Transcript, Analysis Card, slots, and Civic Inbox.

## What Good Looks Like

- The transcript appears as `Final` within a few seconds after you stop speaking.
- Department, issue, priority, sentiment, and slots update after each turn.
- The assistant asks one question at a time.
- Location does not get polluted by time/frequency text.
- Confirmation is short, clean, and human-readable.
- Verified closure includes ticket ID, lookup instruction, SMS mention, and courteous ending.
- If the caller is confused, urgent, or frustrated, optional questions stop and the system moves to verification or human takeover.

## Core Happy Path

### 1. English Power-Cut Intake
Say:
> I am facing too many electrical cuts at my house near Esplanade Apartments on 100 Feet Road.

Expected:
- `department=BESCOM`
- `issue=power_outage`
- Location candidate appears.
- If enough location is detected, next slot should be `started_at_or_time`, not `location`.

Say:
> It has been happening for the past two weeks. In the last three days we had seven cuts, and one lasted three hours.

Expected:
- Priority becomes `MEDIUM` or `HIGH`.
- `started_at_or_time` and `frequency` are stored.
- Landmark remains `Esplanade Apartments...`; it must not become `... It occurs`.

Say:
> No, not yet. We do not know what to do.

Expected:
- Sentiment may become `confused`.
- Optional questioning should stop.
- Assistant should verify the issue and route to BESCOM.

Say:
> Yes, that is correct.

Expected:
- `VERIFIED`
- Ticket ID logged.
- Civic Inbox detailed view has full conversation and extracted fields.

## Location Edge Cases

### 2. Misheard Landmark
Say:
> Power cuts near Espelad Apartments.

Expected:
- Map/location candidate for `Esplanade Apartments`.
- Required slot may become `location_confirm`.
- Assistant asks if the heard place is correct.

Say:
> Yes, that is correct.

Expected:
- `location_validation_status=map_confirmed`
- `location_confirmed=true`

### 3. Broad Major Location
Say:
> Power cut at Airport.

Expected:
- System should not accept this as dispatch-ready.
- It should ask for terminal, gate, road, ward, or a smaller landmark.

### 4. Fake or Test Location
Say:
> Power cut at Whitefield near Vydehi hospital but this is a dummy location.

Expected:
- `location_validation_status=needs_correction`
- Ticket should not be ready.

### 5. Browser Map Pin
In debug mode, click **Send Pin**.

Expected:
- `location_resolution` event appears.
- `location_source=map_pin`
- If the pin is inside service bounds, `location_validation_status=pin_verified`.

## Conversation Quality

### 6. Caller Asks for Clarification
After the assistant confirms, say:
> What do you mean by that?

Expected:
- Assistant explains cleanly and asks confirmation again.
- It should not re-run the whole intake as a new grievance.
- It should not include garbage phrases like `it occurs`.

### 7. Caller Says Just Log It
Say:
> Just create the ticket.

Expected:
- Optional questions stop.
- Assistant verifies required fields immediately.

### 8. Previous Complaint
Say:
> I already complained. Ticket number BES123.

Expected:
- `previous_complaint` is stored.
- Confirmation includes the actual issue/location, not the complaint text as location.

## Distress and Human Takeover

### 9. Safety Issue
Say:
> There is sparking from a wire near the school. It is unsafe.

Expected:
- Priority `HIGH`.
- Human takeover should trigger or be strongly indicated.
- Assistant should say it is connecting to a human operator.

### 10. Repeated Misunderstanding
Give unclear or contradictory corrections twice.

Expected:
- System says it may not be capturing correctly.
- `SAFE_HUMAN_TAKEOVER` triggers.

## Multilingual Checks

### 11. Hindi
Select Hindi.
Say:
> Mere ghar ke paas baar baar bijli ja rahi hai, Whitefield Vydehi hospital ke paas.

Expected:
- Assistant continues in Hindi.
- Department `BESCOM`.
- It should not switch back to English.

### 12. Kannada / Code-Mix
Select Kannada.
Say:
> Whitefield Vydehi hospital hattira current hogide.

Expected:
- Assistant continues in Kannada.
- Department `BESCOM`.
- Transcript and slots update normally.

## Twilio Readiness Checklist

Before calling Twilio:
- Browser debug mic can complete the happy path.
- Live Transcript does not show repeated duplicate events for one turn.
- Location stays clean after time/frequency answers.
- TTS starts in under 3 seconds for short prompts in browser debug.
- `STT: empty_transcript` does not appear repeatedly in browser debug.
- Civic Inbox detailed view shows conversation turns and extracted memory.

During Twilio:
- Confirm `AUDIO: speech_started`.
- Confirm `STT: audio_end_received`.
- Confirm `STT: transcript_ready`.
- If `empty_transcript` repeats, stop and debug audio transport before demo.
