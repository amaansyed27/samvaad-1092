import asyncio
import uuid
import random
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import init_db, get_session, CallRecord

# Extended Synthetic Data for Demo
STATUSES = ["PENDING", "ESCALATED", "RESOLVED"]
LANGUAGES = ["en-IN", "kn-IN", "hi-IN", "ta-IN", "te-IN", "ml-IN"]
SENTIMENTS = ["frustrated", "calm", "annoyed", "neutral", "angry"]

# Complex tuples: (Raw Transcript, Dept, Issue Type, Priority, Location Hint, Cultural Context, Key Details List)
COMPLAINTS_BASE = [
    # BESCOM (Electricity)
    (
        "Hello sir, I am calling from Koramangala 4th Block, near the Sony World signal. There is no power since yesterday 10 PM. We tried calling the local lineman but no response.", 
        "BESCOM", "Power Outage", "HIGH", "Koramangala 4th Block, near Sony World signal", 
        "Caller specifically mentions lack of response from local lineman, indicating frustration with local officials.", 
        ["Power off since 10 PM yesterday", "No response from local lineman"]
    ),
    (
        "Current hogide sir, HSR Layout Sector 2 nalli. Eradu gante aithu, please help.", 
        "BESCOM", "Power Outage", "MEDIUM", "HSR Layout Sector 2", 
        "Spoken in Kannada. 'Current hogide' is a common colloquialism for power cut.", 
        ["Power off for 2 hours"]
    ),
    (
        "The transformer box on 100ft road Indiranagar is sparking heavily and smoking. Send someone immediately before it catches fire!", 
        "BESCOM", "Electrical Hazard", "CRITICAL", "100ft road Indiranagar", 
        "High urgency. Potential fire hazard from municipal infrastructure.", 
        ["Transformer sparking and smoking", "Potential fire hazard"]
    ),
    (
        "Voltage is fluctuating wildly in Jayanagar 9th block. It already damaged my TV and fridge. Please fix the phase issue.", 
        "BESCOM", "Voltage Issue", "MEDIUM", "Jayanagar 9th block", 
        "Caller is claiming property damage due to civic infrastructure failure.", 
        ["Voltage fluctuating wildly", "Home appliances damaged"]
    ),
    
    # BBMP (Municipality/Roads/Waste)
    (
        "Sir, there is a massive pothole right in the middle of the Outer Ring Road near Bellandur ecospace. Two bikers fell down this morning.", 
        "BBMP", "Road Damage", "HIGH", "Outer Ring Road near Bellandur Ecospace", 
        "Safety hazard reported on a major tech corridor. Public safety at risk.", 
        ["Massive pothole in middle of road", "Two accidents already occurred"]
    ),
    (
        "Garbage has not been collected in Malleshwaram 3rd Main for four days. Dogs are tearing the covers and it stinks.", 
        "BBMP", "Waste Management", "LOW", "Malleshwaram 3rd Main", 
        "Standard municipal complaint regarding solid waste management delay.", 
        ["Garbage not collected for 4 days", "Stray dog nuisance causing mess"]
    ),
    (
        "Someone is illegally burning waste leaves and plastic near the BBMP park in BTM Layout. So much toxic smoke.", 
        "BBMP", "Pollution", "MEDIUM", "BBMP park in BTM Layout", 
        "Air pollution violation.", 
        ["Illegal burning of plastic/waste", "Toxic smoke in residential area"]
    ),
    (
        "A huge tree branch fell during the rain and is completely blocking the 1st cross road in Basavanagudi.", 
        "BBMP", "Obstruction", "HIGH", "1st cross road in Basavanagudi", 
        "Monsoon related civic obstruction requiring immediate clearance.", 
        ["Fallen tree branch blocking road", "Caused by recent rain"]
    ),
    
    # BWSSB (Water/Sewage)
    (
        "No Cauvery drinking water supply in Whitefield Phase 1 since yesterday morning. We are relying on expensive tankers.", 
        "BWSSB", "Water Supply", "HIGH", "Whitefield Phase 1", 
        "Mentions 'Cauvery water', a highly specific Bangalore term for municipal piped drinking water.", 
        ["No municipal water since yesterday morning", "Relying on private tankers"]
    ),
    (
        "Underground drainage is overflowing right in front of the Majestic bus stand entrance. It smells terrible and people can't walk.", 
        "BWSSB", "Sewage Overflow", "HIGH", "Majestic bus stand entrance", 
        "High foot-traffic area affected by sewage, major public nuisance.", 
        ["Drainage overflowing onto street", "Terrible smell and blockage"]
    ),
    (
        "We suspect sewage water is mixing with our drinking water line in Rajajinagar 4th Block. The tap water is yellowish and smells foul.", 
        "BWSSB", "Contamination", "CRITICAL", "Rajajinagar 4th Block", 
        "Public health crisis. Requires immediate water testing.", 
        ["Sewage mixing with drinking water", "Water is yellow and smells foul"]
    ),
    (
        "There is a huge water leak from the main BWSSB pipe near the Silk Board junction. Thousands of liters wasting.", 
        "BWSSB", "Pipe Burst", "MEDIUM", "Silk Board junction", 
        "Resource wastage at a major traffic bottleneck.", 
        ["Main pipe burst", "Large scale water wastage"]
    ),
    
    # BMTC (Transport)
    (
        "Bus number 500D did not stop at the Kadubeesanahalli designated stop even though it was empty. The driver just drove past.", 
        "BMTC", "Service Issue", "LOW", "Kadubeesanahalli bus stop", 
        "Complaint against specific route operator behavior.", 
        ["Bus 500D ignored stop", "Bus was empty"]
    ),
    (
        "The conductor on the Volvo AC bus to Airport was very rude and refused to give back my 50 rupees change.", 
        "BMTC", "Staff Behavior", "MEDIUM", "Volvo Airport Route", 
        "Financial/behavioral complaint against government staff.", 
        ["Conductor refused to return change", "Rude behavior"]
    ),
    
    # RTO (Licensing)
    (
        "I submitted my documents for a driving license renewal at the Yeshwanthpur RTO 3 months ago and haven't received my smart card.", 
        "RTO", "Document Delay", "LOW", "Yeshwanthpur RTO", 
        "Standard administrative delay grievance.", 
        ["DL renewal delayed by 3 months", "Smart card not received"]
    ),
    (
        "An agent outside the Electronic City RTO is demanding a 2000 rupee bribe to clear my vehicle registration inspection.", 
        "RTO", "Corruption", "HIGH", "Electronic City RTO", 
        "Vigilance issue. Caller reporting direct bribery by middlemen.", 
        ["Agent demanding 2000 INR bribe", "Issue regarding vehicle registration"]
    ),
    
    # OTHER (Outliers/Noise)
    (
        "Hello, can you tell me where the nearest post office is located near MG Road?", 
        "OTHER", "Information", "LOW", "MG Road", 
        "Non-grievance. Caller seeking general directory information.", 
        ["Seeking post office location"]
    ),
    (
        "My Jio internet is completely down since morning, I need to work from home.", 
        "OTHER", "Telecom", "LOW", "Not specified", 
        "Private sector complaint routed to government helpline.", 
        ["Internet down since morning"]
    )
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
        print("Seeding hyper-realistic civic data...")
        
        # Clear existing for fresh seed
        from sqlalchemy import text
        await db.execute(text("DELETE FROM call_records;"))
        await db.execute(text("DELETE FROM ml_training_data;"))
        
        for i in range(200): # Substantial dataset
            base = random.choice(COMPLAINTS_BASE)
            raw_text = add_noise_to_transcript(base[0])
            
            call_id = uuid.uuid4().hex[:12]
            
            if random.random() > 0.7:
                days_ago = random.randint(2, 14)
            else:
                days_ago = random.uniform(0, 2)
                
            started_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
            completed_at = started_at + timedelta(minutes=random.uniform(0.5, 8.0))
            
            dept = base[1]
            emergency_type = base[2]
            priority = base[3]
            location_hint = base[4]
            cultural_context = base[5]
            key_details = base[6]
            
            distress_level = "CRITICAL" if priority == "CRITICAL" else random.choice(["LOW", "MODERATE", "HIGH"])
            distress_score = random.uniform(0.8, 1.0) if distress_level == "CRITICAL" else random.uniform(0.0, 0.7)
            sentiment = "angry" if priority == "CRITICAL" else random.choice(SENTIMENTS)
            
            confidence = random.uniform(0.75, 0.99)
            if "uh" in raw_text or "um" in raw_text:
                confidence -= random.uniform(0.05, 0.15)
                
            if priority == "CRITICAL":
                status = random.choice(["ESCALATED", "RESOLVED"])
            else:
                status = random.choices(STATUSES, weights=[0.4, 0.1, 0.5])[0]
                
            caller_confirmed = random.random() > 0.10 # 90% confirmation rate
            state = "VERIFIED" if caller_confirmed else "HUMAN_TAKEOVER"
            agent_edited = random.random() > 0.85 
            
            record = CallRecord(
                call_id=call_id,
                state=state,
                language_detected=random.choices(LANGUAGES, weights=[0.5, 0.2, 0.15, 0.05, 0.05, 0.05])[0],
                raw_transcript=raw_text,
                scrubbed_transcript=raw_text, 
                restated_summary=f"I understand you are reporting an issue with {emergency_type.lower()}. Is that correct?",
                emergency_type=emergency_type,
                department_assigned=dept,
                resolution_status=status,
                priority=priority,
                severity=priority.lower(),
                sentiment=sentiment,
                location_hint=location_hint,
                cultural_context=cultural_context,
                key_details=key_details,
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
        print("Successfully seeded database with 200 hyper-realistic records featuring rich metadata.")

if __name__ == "__main__":
    asyncio.run(seed())
