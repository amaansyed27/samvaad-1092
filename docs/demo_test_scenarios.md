# Samvaad 1092 Read-Aloud Demo Test Script

Use this as a live cheat sheet before the Twilio demo. Start the dashboard at `http://localhost:5173`, select the language, then read the caller lines exactly or close to exactly. Watch the Live Transcript, Analysis Card, Verification Slots, and Civic Inbox.

## Fast Pass Checklist

Before judging or recording:

- Transcript shows `Final:` after each caller turn.
- Assistant asks one question at a time.
- Location stays clean after time/frequency/reference answers.
- `request_type`, `department`, `line_department`, `priority`, and `sentiment` update.
- Optional questions stop when caller is urgent, confused, scared, or says "just log it".
- Confirmation is short and human-readable.
- Closure includes ticket ID, status lookup instruction, SMS mention, reassurance, and thanks.
- Civic Inbox detailed view shows full conversation and extracted memory.

## 1. BESCOM Power-Cut Happy Path

Goal: show natural civic intake, clean location, priority from impact, and ticket closure.

Say:
> I am facing too many electrical cuts at my house near Esplanade Apartments on 100 Feet Road, Indiranagar.

Dashboard should show:
- `request_type=grievance`
- `department=BESCOM`
- `issue=power_outage`
- `line_department=BESCOM`
- Location around `Esplanade Apartments` / `Indiranagar`

Assistant should ask something like:
> When did this start, or when does it usually happen?

Say:
> It has been happening for the past two weeks. In the last three days we had seven cuts, and one lasted over three hours.

Dashboard should show:
- `priority=MEDIUM` or `HIGH`
- Time/frequency stored
- Landmark should still be `Esplanade Apartments...`, not the time text

Assistant may ask if you contacted BESCOM before.

Say:
> No, not yet. We do not know what to do.

Expected:
- Sentiment may become `confused`
- Optional questions stop
- Assistant verifies and routes to BESCOM

Say:
> Yes, that is correct.

Expected:
- `VERIFIED`
- Ticket ID appears
- Closure mentions 1092 status lookup and SMS

## 2. Ration Card Janaspandana Case

Goal: show this is not only BESCOM/BBMP, but public grievance intake.

Say:
> My ration card application is pending for two months in Mysuru.

Dashboard should show:
- `request_type=grievance`
- `department=FOOD_CIVIL_SUPPLIES`
- `line_department=Food and Civil Supplies department`
- `issue=ration_card`
- `service_or_scheme=ration card`
- `area=Mysuru`

Assistant should ask for application/reference.

Say:
> It is linked with the same mobile number.

Expected:
- It should not ask the same question again.
- It should store reference as caller mobile number or equivalent.
- Location must remain `Mysuru`, not `Mysuru. It is linked...`
- Assistant should verify cleanly.

Say:
> Yes, please register it.

Expected:
- Ticket logged with Food and Civil Supplies
- Closure has ticket ID and status lookup

## 3. Labour Wages Complaint

Goal: show department routing for worker grievance.

Say:
> The labour office is not responding about unpaid wages from my employer in Peenya.

Dashboard should show:
- `department=LABOUR`
- `issue=labour_grievance`
- `line_department=Labour department`
- Service detail around wages/labour office
- Area/location around `Peenya`

If asked for office or employer, say:
> It is the Peenya labour office. The employer has not paid for one month.

Expected:
- Caller tried/office detail should be captured
- Assistant should verify, not keep collecting forever

## 4. Government Hospital Medicine Complaint

Goal: show Health department and priority based on described impact.

Say:
> Government hospital staff refused medicine for my child in Jayanagar.

Dashboard should show:
- `department=HEALTH`
- `issue=health_service`
- `line_department=Health and Family Welfare department`
- Relevant helpline `104`
- `priority=MEDIUM` or `HIGH`

If assistant asks for more detail, say:
> It happened today morning at the government hospital, and my child needs the medicine.

Expected:
- Health impact remains visible
- Assistant should reassure and verify quickly

## 5. Pension / Welfare Delay

Goal: show scheme/public-service grievance.

Say:
> My old age pension has not been received for three months in Tumakuru.

Dashboard should show:
- `department=SOCIAL_WELFARE`
- `issue=pension_delay`
- `service_or_scheme=pension`
- `area=Tumakuru`

If asked for reference, say:
> I do not have the number. Please use my mobile number.

Expected:
- It should accept mobile/reference fallback
- It should proceed to verification

## 6. Streetlights + Women Safety Context

Goal: show nuanced understanding: not just road issue, but safety concern.

Say:
> There are no street lights on the road from the metro to my house. I have to walk there at night. It is a very shady area and I do not feel safe. People keep staring at me. Please help.

Dashboard should show:
- `department=BBMP`
- `issue=streetlights`
- Priority should become `HIGH`
- Safety concern in priority reason or key details
- It should ask for exact metro station, road, or landmark

If asked for exact place, say:
> It is from Indiranagar metro station towards 5th Cross, near Esplanade Apartments.

Expected:
- Location becomes specific
- Assistant should not treat fear text as location
- It may verify or escalate depending distress

## 7. Immediate Safety Emergency

Goal: show safe handoff instead of form-filling.

Say:
> Someone is following me right now near Majestic bus stop. I am scared.

Dashboard should show:
- `request_type=emergency_referral`
- `department=POLICE`
- `specialized_helpline=100`
- `requires_immediate_takeover=true`

Assistant should say:
> I am connecting you to a human operator now. Please stay on the line.

Expected:
- No optional questions
- `SAFE_HUMAN_TAKEOVER`

## 8. Contaminated Water + Health Note

Goal: show cross-department understanding.

Say:
> Water is contaminated near Whitefield and my child is sick after drinking it.

Dashboard should show:
- Primary `department=BWSSB`
- Secondary note should mention `HEALTH`
- Priority `MEDIUM` or `HIGH`
- Key details should not hide the health risk

If asked for exact location, say:
> It is near Vydehi Hospital, Whitefield.

Expected:
- Route primary grievance to BWSSB
- Add health concern/operator note

## 9. Misheard Landmark Correction

Goal: show map/location confirmation.

Say:
> Power cuts near Espelad Apartments.

Dashboard should show:
- Candidate for `Esplanade Apartments`
- `required_slot=location_confirm`
- Assistant asks whether the heard place is correct

Say:
> Yes, that is correct.

Expected:
- `location_validation_status=map_confirmed`
- `location_confirmed=true`
- It proceeds to optional time or verification

## 10. Broad Landmark Guardrail

Goal: show it does not dispatch to vague famous places.

Say:
> Power cut at Airport.

Expected:
- Ticket should not be ready
- `location_validation_status=needs_correction`
- Assistant asks for terminal, gate, road, ward, or smaller landmark

Say:
> Near Terminal 2 arrival gate, Kempegowda airport.

Expected:
- Location becomes more usable

## 11. Fake / Dummy Location Guardrail

Goal: show spam/fake detection without blacklisting genuine callers.

Say:
> Power cut at Whitefield near Vydehi hospital but this is a dummy location.

Expected:
- `location_validation_status=needs_correction`
- Ticket should not be ready
- Assistant should ask for the real location

If asked again, say:
> Sorry, real location is Whitefield near Vydehi Hospital.

Expected:
- It should recover and continue

## 12. Caller Says Just Log It

Goal: show optional questions stop.

Start with:
> Power cut at Whitefield near Vydehi Hospital.

When assistant asks optional time/frequency, say:
> Just create the ticket.

Expected:
- Optional questions stop
- Assistant verifies required fields immediately

## 13. Previous Complaint Number

Goal: show previous-ticket capture.

Say:
> Power cuts near Vydehi Hospital, Whitefield. I already complained. Ticket number BES123.

Expected:
- `department=BESCOM`
- `previous_complaint` includes `BES123`
- Location remains `Vydehi Hospital, Whitefield`
- Confirmation should not use the complaint number as location

## 14. Caller Asks "What Do You Mean?"

Goal: show repair during confirmation.

Run any normal flow until confirmation, then say:
> What do you mean by that?

Expected:
- Assistant explains the clean summary again
- It should not restart intake
- It should not include junk phrases like `it occurs`

## 15. Repeated Misunderstanding

Goal: show safe human takeover.

Say unclear or contradictory corrections twice, for example:
> No, that is wrong.

Then:
> No, you are still not getting it.

Expected:
- Assistant says it may not be capturing correctly
- `SAFE_HUMAN_TAKEOVER`
- Caller does not have to repeat forever

## 16. Spam / No Issue

Goal: show prank guardrail.

Say:
> This is a prank test call haha no issue.

Expected:
- `request_type=spam_or_prank` or abuse guardrail warning
- No ticket should be logged
- Assistant asks for a real issue/location if help is needed

## 17. Hindi Power-Cut Check

Select Hindi.

Say:
> Mere ghar ke paas baar baar bijli ja rahi hai, Whitefield Vydehi hospital ke paas.

Expected:
- Assistant continues in Hindi
- `department=BESCOM`
- `issue=power_outage`
- It should not switch back to English

If asked time, say:
> Pichle ek hafte se ho raha hai.

Expected:
- Time detail is stored
- Verification is in Hindi

## 18. Kannada / Code-Mix Power Check

Select Kannada.

Say:
> Whitefield Vydehi hospital hattira current hogide.

Expected:
- Assistant continues in Kannada
- `department=BESCOM`
- `issue=power_outage`
- Transcript and slots update normally

If asked for time, say:
> Eradu dinadinda aguttide.

Expected:
- It should continue the Kannada flow

## 19. Browser Map Pin Flow

Goal: show geo pointing when speech location is hard.

Say:
> I am near a small lane but I cannot explain the exact address.

Then click **Send Pin** in debug mode.

Expected:
- `location_resolution` event appears
- `location_source=map_pin`
- `location_validation_status=pin_verified`
- Ticket can proceed with pin location

## 20. Twilio Readiness Smoke Test

Use this exact short call before the judge demo:

Say:
> Power cut at Whitefield near Vydehi Hospital.

Then:
> It has been happening every night.

Then:
> Yes, that is correct.

Expected logs:
- `Audio: twilio speech_started`
- `STT: audio end received`
- `STT: transcript ready`
- `Assistant audio started`
- No repeated `STT: empty transcript`
- No repeated duplicate assistant prompt
- Total turn gap should feel conversational

If Twilio repeats `empty transcript`, stop and debug audio transport before demo.
