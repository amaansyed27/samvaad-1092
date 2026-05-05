import joblib
import os
import logging
from typing import Dict, Any

logger = logging.getLogger("samvaad.ml_routing")

_classifier = None

def get_classifier():
    global _classifier
    if _classifier is None:
        model_path = os.path.join(os.path.dirname(__file__), "..", "models", "dept_classifier.joblib")
        if os.path.exists(model_path):
            _classifier = joblib.load(model_path)
            logger.info("Loaded local ML department classifier.")
        else:
            logger.warning(f"Department classifier not found at {model_path}. Run train_dept_classifier.py")
    return _classifier

def predict_department(transcript: str) -> Dict[str, Any]:
    """
    Use local Naive Bayes classifier to instantly predict the civic department.
    """
    if not transcript or len(transcript.strip()) == 0:
        return {"department": "UNKNOWN", "confidence": 0.0}
        
    clf = get_classifier()
    if not clf:
        return {"department": "UNKNOWN", "confidence": 0.0}
        
    try:
        pred = clf.predict([transcript])[0]
        probs = clf.predict_proba([transcript])[0]
        confidence = float(max(probs))
        
def retrain_classifier(new_data: list[Dict[str, Any]]) -> bool:
    """
    Retrain the local ML model using synthetic base data + new active learning data.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.pipeline import Pipeline
    import os
    
    # Base synthetic data so the model doesn't forget its foundation
    TRAINING_DATA = [
        ("power cut", "BESCOM"), ("no electricity", "BESCOM"), ("transformer sparked", "BESCOM"), 
        ("streetlights not working", "BESCOM"), ("power fluctuation", "BESCOM"), ("wire snapped", "BESCOM"),
        ("voltage issue", "BESCOM"), ("meter box burnt", "BESCOM"), ("no current", "BESCOM"),
        ("massive pothole", "BBMP"), ("garbage not collected", "BBMP"), ("stray dogs", "BBMP"),
        ("drain blocked", "BBMP"), ("tree fallen on road", "BBMP"), ("illegal construction", "BBMP"),
        ("road damage", "BBMP"), ("waste burning", "BBMP"), ("broken pavement", "BBMP"),
        ("no drinking water supply", "BWSSB"), ("drainage overflow", "BWSSB"), ("water contamination", "BWSSB"),
        ("sewage mixed with water", "BWSSB"), ("pipe burst", "BWSSB"), ("no cauvery water", "BWSSB"),
        ("manhole open", "BWSSB"), ("water leak", "BWSSB"),
        ("loud music late night", "POLICE"), ("suspicious activity", "POLICE"), ("fight on street", "POLICE"),
        ("theft", "POLICE"), ("someone is following me", "POLICE"), ("harassment", "POLICE"),
        ("domestic violence", "POLICE"), ("illegal parking", "POLICE"),
        ("fire caught", "FIRE"), ("building on fire", "FIRE"), ("smoke coming out", "FIRE"),
        ("cylinder blast", "FIRE"), ("shop burning", "FIRE"), ("gas leak", "FIRE")
    ]
    
    X = [item[0] for item in TRAINING_DATA]
    y = [item[1] for item in TRAINING_DATA]
    
    # Append new gold standard corrections
    for row in new_data:
        X.append(row["transcript"])
        y.append(row["department"])
        
    try:
        pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(ngram_range=(1, 2))),
            ('clf', MultinomialNB())
        ])
        
        pipeline.fit(X, y)
        
        model_path = os.path.join(os.path.dirname(__file__), "..", "models", "dept_classifier.joblib")
        joblib.dump(pipeline, model_path)
        
        # Hot-reload in memory
        global _classifier
        _classifier = pipeline
        logger.info(f"Successfully retrained ML model with {len(new_data)} new examples.")
        return True
    except Exception as e:
        logger.error(f"Failed to retrain model: {e}")
        return False
