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
        
        # Threshold: if it's too unsure, return UNKNOWN
        if confidence < 0.2:
            return {"department": "UNKNOWN", "confidence": confidence}
            
        return {"department": pred, "confidence": confidence}
    except Exception as e:
        logger.error(f"ML routing failed: {e}")
        return {"department": "UNKNOWN", "confidence": 0.0}
