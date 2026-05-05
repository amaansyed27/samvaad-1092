import asyncio
import uuid
import random
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import init_db, get_session, CallRecord

# Extended Synthetic Data for Demo
DEPARTMENTS = ["BESCOM", "BBMP", "BWSSB", "POLICE", "FIRE", "OTHER"]
STATUSES = ["PENDING", "ESCALATED", "RESOLVED"]
PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
LANGUAGES = ["en-IN", "kn-IN", "hi-IN", "ta-IN", "te-IN", "ml-IN"]
SENTIMENTS = ["distressed", "calm", "angry", "confused", "panicked"]

COMPLAINTS_BASE = [
    # BESCOM (Electricity)
    ("Power cut in my area for 3 hours", "BESCOM", "Power Outage", "MEDIUM"),
    ("Current hogide sir, please help", "BESCOM", "Power Outage", "MEDIUM"),
    ("Transformer sparked and caught fire near my house", "BESCOM", "Fire/Electrical", "CRITICAL"),
    ("Voltage fluctuation damaged my TV", "BESCOM", "Voltage Issue", "LOW"),
    ("Streetlights on 100ft road are not working", "BESCOM", "Streetlight", "LOW"),
    ("Wire snapped and fell on the road, very dangerous!", "BESCOM", "Hazard", "HIGH"),
    
    # BBMP (Municipality/Roads/Waste)
    ("Massive pothole on the main road caused an accident", "BBMP", "Road Damage", "HIGH"),
    ("Garbage is not collected in Indiranagar for 3 days", "BBMP", "Waste Management", "LOW"),
    ("Stray dogs are chasing kids near the park", "BBMP", "Animal Control", "MEDIUM"),
    ("Tree branch fell blocking the road", "BBMP", "Obstruction", "MEDIUM"),
    ("Illegal construction happening next door", "BBMP", "Code Violation", "LOW"),
    ("Someone is burning waste leaves, so much smoke", "BBMP", "Pollution", "MEDIUM"),
    
    # BWSSB (Water/Sewage)
    ("No drinking water supply since yesterday morning", "BWSSB", "Water Supply", "HIGH"),
    ("Drainage overflowing on the main street, smelling bad", "BWSSB", "Sewage", "MEDIUM"),
    ("Sewage water mixing with drinking water line", "BWSSB", "Contamination", "CRITICAL"),
    ("Huge water leak from the main pipe", "BWSSB", "Pipe Burst", "HIGH"),
    ("Manhole cover is missing, someone might fall", "BWSSB", "Hazard", "CRITICAL"),
    
    # POLICE (Law & Order)
    ("Loud music playing after 11 PM", "POLICE", "Noise Disturbance", "LOW"),
    ("Suspicious people gathering near the ATM", "POLICE", "Suspicious Activity", "MEDIUM"),
    ("Two guys are fighting on the street", "POLICE", "Public Disturbance", "HIGH"),
    ("My bike was stolen from the parking lot", "POLICE", "Theft", "MEDIUM"),
    ("Someone is following me, I feel unsafe", "POLICE", "Harassment", "CRITICAL"),
    ("Domestic violence happening in the next apartment", "POLICE", "Violence", "CRITICAL"),
    
    # FIRE (Fire/Emergency)
    ("A shop caught fire in the market", "FIRE", "Fire Incident", "CRITICAL"),
    ("Thick black smoke coming from the apartment window", "FIRE", "Fire Incident", "CRITICAL"),
    ("Gas cylinder blast in the neighborhood", "FIRE", "Explosion", "CRITICAL"),
    
    # OTHER (Outliers/Noise)
    ("Where is the nearest post office?", "OTHER", "Information", "LOW"),
    ("My internet is not working", "OTHER", "Telecom", "LOW"),
    ("What time does the metro start?", "OTHER", "Information", "LOW")
]

def add_noise_to_transcript(text):
    """Simulate ASR errors and hesitations for realism"""
    noise_elements = [" uh ", " um ", " like ", " you know ", " ah ", " sir ", " madam "]
    words = text.split()
    if random.random() > 0.6:
        insert_idx = random.randint(1, max(1, len(words) - 1))
        words.insert(insert_idx, random.choice(noise_elements).strip())
    
    # Typo simulation
    if random.random() > 0.8:
        target = random.randint(0, len(words) - 1)
        if len(words[target]) > 4:
            char_idx = random.randint(1, len(words[target]) - 2)
            word = list(words[target])
            # Swap two chars
            word[char_idx], word[char_idx+1] = word[char_idx+1], word[char_idx]
            words[target] = "".join(word)
            
    return " ".join(words)

async def seed():
    await init_db()
    async with get_session() as db:
        print("Seeding robust synthetic dataset...")
        
        # Clear existing for fresh seed
        from sqlalchemy import text
        await db.execute(text("DELETE FROM call_records;"))
        await db.execute(text("DELETE FROM ml_training_data;"))
        
        for i in range(250): # Substantial dataset
            base = random.choice(COMPLAINTS_BASE)
            raw_text = add_noise_to_transcript(base[0])
            
            call_id = uuid.uuid4().hex[:12]
            
            # Skew timestamps to look like an active week of operations
            # Heavy concentration in the last 48 hours
            if random.random() > 0.7:
                days_ago = random.randint(2, 14)
            else:
                days_ago = random.uniform(0, 2)
                
            started_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
            completed_at = started_at + timedelta(minutes=random.uniform(0.5, 8.0))
            
            dept = base[1]
            emergency_type = base[2]
            priority = base[3]
            
            # Logic correlation
            distress_level = "CRITICAL" if priority == "CRITICAL" else random.choice(["LOW", "MODERATE", "HIGH"])
            distress_score = random.uniform(0.8, 1.0) if distress_level == "CRITICAL" else random.uniform(0.0, 0.7)
            sentiment = "panicked" if priority == "CRITICAL" else random.choice(SENTIMENTS)
            
            # Simulation of LLM confidence based on noise
            confidence = random.uniform(0.65, 0.99)
            if "uh" in raw_text or "um" in raw_text:
                confidence -= random.uniform(0.1, 0.2)
                
            # Randomize status with bias
            if priority == "CRITICAL":
                status = random.choice(["ESCALATED", "RESOLVED"])
            else:
                status = random.choices(STATUSES, weights=[0.4, 0.1, 0.5])[0]
                
            caller_confirmed = random.random() > 0.15 # 85% confirmation rate
            state = "VERIFIED" if caller_confirmed else "HUMAN_TAKEOVER"
            
            agent_edited = random.random() > 0.85 # 15% agent edit rate
            
            record = CallRecord(
                call_id=call_id,
                state=state,
                language_detected=random.choices(LANGUAGES, weights=[0.4, 0.3, 0.2, 0.05, 0.025, 0.025])[0],
                raw_transcript=raw_text,
                scrubbed_transcript=raw_text, # Assuming clean for basic seed
                restated_summary=f"I understand you are reporting {emergency_type.lower()}. Is that correct?",
                emergency_type=emergency_type,
                department_assigned=dept,
                resolution_status=status,
                priority=priority,
                severity=priority.lower(),
                sentiment=sentiment,
                confidence=round(confidence, 2),
                distress_score=round(distress_score, 2),
                distress_level=distress_level,
                caller_confirmed=caller_confirmed,
                agent_edited=agent_edited,
                started_at=started_at,
                completed_at=completed_at,
                pii_entities_count=random.randint(0, 2) if random.random() > 0.8 else 0
            )
            db.add(record)
            
        await db.commit()
        print("Successfully seeded database with 250 diverse records featuring synthetic noise and correlations.")

if __name__ == "__main__":
    asyncio.run(seed())
