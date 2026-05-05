import joblib
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

# Synthetic data mapping civic keywords to Karnataka departments
TRAINING_DATA = [
    # BESCOM (Electricity)
    ("power cut", "BESCOM"), ("no electricity", "BESCOM"), ("transformer sparked", "BESCOM"), 
    ("streetlights not working", "BESCOM"), ("power fluctuation", "BESCOM"), ("wire snapped", "BESCOM"),
    ("voltage issue", "BESCOM"), ("meter box burnt", "BESCOM"), ("no current", "BESCOM"),
    
    # BBMP (Municipality/Roads/Waste)
    ("massive pothole", "BBMP"), ("garbage not collected", "BBMP"), ("stray dogs", "BBMP"),
    ("drain blocked", "BBMP"), ("tree fallen on road", "BBMP"), ("illegal construction", "BBMP"),
    ("road damage", "BBMP"), ("waste burning", "BBMP"), ("broken pavement", "BBMP"),
    
    # BWSSB (Water/Sewage)
    ("no drinking water supply", "BWSSB"), ("drainage overflow", "BWSSB"), ("water contamination", "BWSSB"),
    ("sewage mixed with water", "BWSSB"), ("pipe burst", "BWSSB"), ("no cauvery water", "BWSSB"),
    ("manhole open", "BWSSB"), ("water leak", "BWSSB"),
    
    # POLICE (Law & Order)
    ("loud music late night", "POLICE"), ("suspicious activity", "POLICE"), ("fight on street", "POLICE"),
    ("theft", "POLICE"), ("someone is following me", "POLICE"), ("harassment", "POLICE"),
    ("domestic violence", "POLICE"), ("illegal parking", "POLICE"),
    
    # FIRE (Fire/Emergency)
    ("fire caught", "FIRE"), ("building on fire", "FIRE"), ("smoke coming out", "FIRE"),
    ("cylinder blast", "FIRE"), ("shop burning", "FIRE"), ("gas leak", "FIRE")
]

def train_and_save():
    X = [item[0] for item in TRAINING_DATA]
    y = [item[1] for item in TRAINING_DATA]
    
    # Create a pipeline with TF-IDF and Naive Bayes
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(ngram_range=(1, 2))),
        ('clf', MultinomialNB())
    ])
    
    print("Training Department Classifier (Naive Bayes)...")
    pipeline.fit(X, y)
    
    # Ensure models dir exists
    os.makedirs(os.path.join('app', 'models'), exist_ok=True)
    
    model_path = os.path.join('app', 'models', 'dept_classifier.joblib')
    joblib.dump(pipeline, model_path)
    print(f"Model saved to {model_path}")
    
    # Test
    test_phrase = "there is a big pothole here"
    pred = pipeline.predict([test_phrase])[0]
    prob = max(pipeline.predict_proba([test_phrase])[0])
    print(f"Test: '{test_phrase}' -> {pred} ({prob:.2f})")

if __name__ == "__main__":
    train_and_save()
