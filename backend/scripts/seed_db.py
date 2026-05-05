import asyncio
import uuid
import random
from datetime import datetime, timedelta, timezone

from app.core.database import init_db, get_session, CallRecord

# Sample data
DEPARTMENTS = ["BESCOM", "BBMP", "BWSSB", "POLICE", "FIRE", "OTHER"]
STATUSES = ["PENDING", "ESCALATED", "RESOLVED"]
PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

COMPLAINTS = [
    ("Power cut in my area for 3 hours", "BESCOM", "Power Outage"),
    ("There is a massive pothole on 100ft road", "BBMP", "Road Damage"),
    ("No drinking water supply since yesterday", "BWSSB", "Water Supply"),
    ("Someone is playing loud music late at night", "POLICE", "Noise Disturbance"),
    ("Garbage is not collected in Indiranagar", "BBMP", "Waste Management"),
    ("Transformer sparked and caught fire", "FIRE", "Fire Incident", "CRITICAL"),
    ("Streetlights are not working", "BESCOM", "Streetlight Issue"),
    ("Stray dogs are chasing kids", "BBMP", "Animal Control"),
    ("Drainage overflow on main road", "BWSSB", "Sewage Issue"),
    ("Suspicious activity near the park", "POLICE", "Suspicious Activity")
]

async def seed():
    await init_db()
    async with get_session() as db:
        for _ in range(50):
            complaint = random.choice(COMPLAINTS)
            call_id = uuid.uuid4().hex[:12]
            started_at = datetime.now(timezone.utc) - timedelta(days=random.randint(0, 10), hours=random.randint(0, 24))
            completed_at = started_at + timedelta(minutes=random.randint(1, 10))
            
            priority = complaint[3] if len(complaint) > 3 else random.choice(PRIORITIES)
            
            record = CallRecord(
                call_id=call_id,
                state="VERIFIED",
                language_detected=random.choice(["en-IN", "kn-IN", "hi-IN"]),
                raw_transcript=complaint[0],
                scrubbed_transcript=complaint[0],
                restated_summary=f"You are reporting {complaint[0].lower()}. Is that correct?",
                emergency_type=complaint[2],
                department_assigned=complaint[1],
                resolution_status=random.choice(STATUSES),
                priority=priority,
                severity=priority.lower(),
                sentiment="distressed",
                caller_confirmed=True,
                started_at=started_at,
                completed_at=completed_at
            )
            db.add(record)
            
        await db.commit()
        print("Successfully seeded database with 50 records.")

if __name__ == "__main__":
    asyncio.run(seed())
