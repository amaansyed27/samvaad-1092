import joblib
import os
import random
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

# Extended Synthetic Data for Robust Training Baseline
# Includes variations, code-mixed phrases, and noise to prevent overfitting
TRAINING_DATA = [
    # BESCOM (Electricity)
    ("power cut", "BESCOM"), ("no electricity", "BESCOM"), ("transformer sparked", "BESCOM"), 
    ("streetlights not working", "BESCOM"), ("power fluctuation", "BESCOM"), ("wire snapped", "BESCOM"),
    ("voltage issue", "BESCOM"), ("meter box burnt", "BESCOM"), ("no current", "BESCOM"),
    ("current hogide", "BESCOM"), ("bijli nahi hai", "BESCOM"), ("power gone since morning", "BESCOM"),
    ("sparking in the electric pole", "BESCOM"), ("line broken", "BESCOM"), ("frequent power trips", "BESCOM"),
    
    # BBMP (Municipality/Roads/Waste)
    ("massive pothole", "BBMP"), ("garbage not collected", "BBMP"), ("stray dogs", "BBMP"),
    ("drain blocked", "BBMP"), ("tree fallen on road", "BBMP"), ("illegal construction", "BBMP"),
    ("road damage", "BBMP"), ("waste burning", "BBMP"), ("broken pavement", "BBMP"),
    ("kachra is overflowing", "BBMP"), ("road is completely broken", "BBMP"), ("street dogs attacking", "BBMP"),
    ("building without permission", "BBMP"), ("footpath broken", "BBMP"), ("smoke from burning trash", "BBMP"),
    
    # BWSSB (Water/Sewage)
    ("no drinking water supply", "BWSSB"), ("drainage overflow", "BWSSB"), ("water contamination", "BWSSB"),
    ("sewage mixed with water", "BWSSB"), ("pipe burst", "BWSSB"), ("no cauvery water", "BWSSB"),
    ("manhole open", "BWSSB"), ("water leak", "BWSSB"),
    ("pani nahi aa raha", "BWSSB"), ("neeru bandilla", "BWSSB"), ("drinking water smells bad", "BWSSB"),
    ("underground drain leaking", "BWSSB"), ("water supply line broken", "BWSSB"), ("dirty water coming", "BWSSB"),
    
    # POLICE (Law & Order)
    ("loud music late night", "POLICE"), ("suspicious activity", "POLICE"), ("fight on street", "POLICE"),
    ("theft", "POLICE"), ("someone is following me", "POLICE"), ("harassment", "POLICE"),
    ("domestic violence", "POLICE"), ("illegal parking", "POLICE"),
    ("someone stole my bike", "POLICE"), ("goondas making trouble", "POLICE"), ("assault happening", "POLICE"),
    ("neighbor is beating his wife", "POLICE"), ("drunk people shouting", "POLICE"), ("pickpocket", "POLICE"),
    
    # FIRE (Fire/Emergency)
    ("fire caught", "FIRE"), ("building on fire", "FIRE"), ("smoke coming out", "FIRE"),
    ("cylinder blast", "FIRE"), ("shop burning", "FIRE"), ("gas leak", "FIRE"),
    ("aag lag gayi", "FIRE"), ("benki biddide", "FIRE"), ("house is burning", "FIRE"),
    ("explosion in factory", "FIRE"), ("flames everywhere", "FIRE"), ("car caught fire", "FIRE"),
    
    # OTHER (Outliers/Noise/Non-Actionable)
    ("what is the time?", "OTHER"), ("hello can you hear me", "OTHER"), ("where is the nearest hospital", "OTHER"),
    ("i want to book a ticket", "OTHER"), ("internet is slow", "OTHER"), ("how to apply for passport", "OTHER"),
    ("is it going to rain today", "OTHER"), ("my phone is not working", "OTHER"), ("i need a job", "OTHER")
]

def add_noise_to_phrase(text):
    """Introduce slight permutations to generate a larger synthetic dataset"""
    words = text.split()
    if len(words) < 2:
        return text
    if random.random() > 0.7:
        # Swap two random words
        idx1, idx2 = random.sample(range(len(words)), 2)
        words[idx1], words[idx2] = words[idx2], words[idx1]
    return " ".join(words)

def generate_augmented_data():
    augmented = []
    for phrase, label in TRAINING_DATA:
        augmented.append((phrase, label))
        # Add 3 noisy variants per original phrase
        for _ in range(3):
            noisy_phrase = add_noise_to_phrase(phrase)
            # Add prefix/suffix padding occasionally
            if random.random() > 0.5:
                noisy_phrase = "sir " + noisy_phrase
            if random.random() > 0.5:
                noisy_phrase = noisy_phrase + " please help"
            augmented.append((noisy_phrase, label))
    return augmented

def train_and_save():
    print("Generating augmented dataset...")
    full_dataset = generate_augmented_data()
    print(f"Dataset expanded to {len(full_dataset)} samples.")
    
    X = [item[0] for item in full_dataset]
    y = [item[1] for item in full_dataset]
    
    # Pipeline with strong regularization to prevent overfitting on this synthetic baseline
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True, max_df=0.5)),
        ('clf', MultinomialNB(alpha=0.5)) # Smoothing for unigrams
    ])
    
    print("Training Robust Department Classifier (Naive Bayes)...")
    pipeline.fit(X, y)
    
    os.makedirs(os.path.join('app', 'models'), exist_ok=True)
    
    model_path = os.path.join('app', 'models', 'dept_classifier.joblib')
    joblib.dump(pipeline, model_path)
    print(f"Model saved to {model_path}")
    
    # Testing
    test_phrases = [
        "there is a big pothole here",
        "current totally gone in my house",
        "my neighbor is being beaten up",
        "how to get an aadhaar card"
    ]
    
    for phrase in test_phrases:
        pred = pipeline.predict([phrase])[0]
        prob = max(pipeline.predict_proba([phrase])[0])
        print(f"Test: '{phrase}' -> {pred} ({prob:.2f})")

if __name__ == "__main__":
    train_and_save()
