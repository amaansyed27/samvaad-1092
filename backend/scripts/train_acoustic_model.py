import os
import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score

def generate_synthetic_data(samples=5000):
    """
    Generate synthetic acoustic feature data to train our model.
    Features: energy, centroid, zcr, mfcc_var
    Target: distress_score (0.0 to 1.0)
    """
    np.random.seed(42)
    
    # Generate random features between 0 and 1
    energy = np.random.beta(2, 5, samples)     # Skewed towards lower energy
    centroid = np.random.beta(2, 5, samples)   # Skewed towards lower pitch
    zcr = np.random.beta(2, 5, samples)        # Skewed towards less noise
    mfcc_var = np.random.beta(2, 5, samples)   # Skewed towards stable speech
    
    # Introduce emergency correlations
    # Emergencies typically have high energy (screaming), high centroid (shrill), high mfcc variance (panic)
    # We create a complex non-linear relationship
    base_distress = (0.45 * energy) + (0.30 * centroid) + (0.10 * zcr) + (0.15 * mfcc_var)
    
    # Non-linear boost for extreme energy (screaming)
    boost = np.where(energy > 0.7, 0.2, 0.0)
    
    # Add some random noise
    noise = np.random.normal(0, 0.05, samples)
    
    target = np.clip(base_distress + boost + noise, 0.0, 1.0)
    
    X = np.column_stack((energy, centroid, zcr, mfcc_var))
    y = target
    
    return X, y

def main():
    print("Generating synthetic acoustic data...")
    X, y = generate_synthetic_data()
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print("Training custom Random Forest Regressor...")
    model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    print(f"Model trained! MSE: {mse:.4f}, R2: {r2:.4f}")
    
    # Save the model
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "models")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, "acoustic_rf.joblib")
    
    joblib.dump(model, model_path)
    print(f"Model saved to {model_path}")

if __name__ == "__main__":
    main()
