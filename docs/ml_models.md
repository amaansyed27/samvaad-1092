# Machine Learning & AI in Samvaad 1092

The Samvaad 1092 platform utilizes a carefully balanced **Hybrid AI Architecture**. It pairs ultra-fast, local Machine Learning models (for split-second triage and safety) with heavy, cloud-based Large Language Models (for deep cognitive understanding and dialect translation).

---

## 1. Fast Local ML: The Department Classifier

Traditional help-desk systems use slow IVR trees or rely entirely on slow LLMs. Samvaad 1092 intercepts the raw transcript and uses a local Scikit-Learn model to predict the intended government department in **under 5 milliseconds**.

### Architecture
- **Algorithm**: Multinomial Naive Bayes (`MultinomialNB`) coupled with Term Frequency-Inverse Document Frequency (`TfidfVectorizer`).
- **Features**: N-gram range of (1, 3) to capture contextual phrases (e.g., "power cut", "drinking water"). Sublinear TF scaling is applied to prevent repetitive words from dominating the feature space.
- **Labels**: `BESCOM` (Electricity), `BBMP` (Municipality), `BWSSB` (Water/Sewage), `POLICE`, `FIRE`, `OTHER` (Outliers/Non-Actionable).

### The Data & Active Learning Strategy
The model starts with a **Synthetic Baseline Dataset** (`scripts/train_dept_classifier.py`). This baseline contains highly augmented, noisy data simulating typographical errors, ASR glitches, and code-mixed phrases (e.g., "Current hogide sir").

However, this baseline is intentionally designed to be superseded. Samvaad 1092 features an **Active Learning Loop**:
1. If the heavy LLM disagrees with the Fast ML's prediction, the system silently records the correction.
2. If a human agent edits the department on the dashboard, the system records it as a "Gold Standard" signal.
3. Operators can trigger the **Deploy Active Learning** endpoint, which recompiles the dataset and hot-reloads the Naive Bayes model in memory, making it immune to repetitive edge-case failures.

---

## 2. Fast Local ML: The Acoustic Guardian

Relying entirely on text transcription for emergencies is dangerous (e.g., screaming might be transcribed as silence).

### Architecture
- **Algorithm**: `RandomForestRegressor` with 100 estimators.
- **Features**: The system extracts raw audio characteristics using `librosa`:
  - **RMS Energy**: The raw volume/loudness of the clip.
  - **Spectral Centroid**: The "brightness" of the sound (screams have high centroids).
  - **Zero-Crossing Rate (ZCR)**: Heavily correlated with percussive noise and high-panic speech.
  - **MFCC Variance**: Captures the timbral fluctuation.

The Acoustic Guardian outputs an `Acoustic Distress Score` (0.0 to 1.0). This score is then fed *into* the LLM Swarm as a parameter, allowing the LLM to cross-reference "how the caller sounds" with "what the caller is saying" to generate a holistic semantic distress verdict.

---

## 3. The LLM Swarm Cascade

To ensure absolute uptime and cognitive depth, Samvaad 1092 does not rely on a single LLM provider. It uses a cascading priority factory.

### Tier 1: Groq (Llama-3)
- **Purpose**: Ultra-low latency Sentiment Analysis.
- **Execution**: Processes the transcript in ~200ms to immediately determine if the caller is distressed, angry, or calm.

### Tier 2: DeepSeek V4 / Nemotron 120B (OpenRouter)
- **Purpose**: Deep Civic Analysis and Dialect Processing.
- **Execution**: These models excel at understanding cultural nuances. They parse the transcript to extract exact administrative locations (Ward, Taluk), severity, and key details. Crucially, they correct any mistakes made by the Fast ML Department Classifier.

### Tier 3: Gemini Flash
- **Purpose**: High-availability fallback. If the primary models hit rate limits or downtime, the system instantly fails over to Gemini.

---

## 4. The Speech Bridge (Sarvam AI)
Audio processing relies on Indian DPI APIs tailored for regional dialects.
- **STT (Saaras V3)**: Converts 16kHz PCM audio to text, automatically detecting the language (Kannada, Hindi, English).
- **TTS (Bulbul V3)**: Synthesizes the AI's restatement into natural-sounding speech in the caller's native language.

### Current STT/TTS Guardrails
- The caller's IVR choice locks the language code for the call (`en-IN`, `kn-IN`, or `hi-IN`).
- Streaming STT is used for low-latency partials. If no final transcript arrives, the backend sends the buffered utterance through Sarvam REST STT.
- The dashboard emits `STT:*` diagnostic events so demo operators can distinguish audio transport failure from STT failure.
- Common civic categories use deterministic guardrails before ML/LLM output is trusted. For example, electrical/current/power-cut phrasing is forced to `BESCOM` and `power_outage` even if the fast classifier is noisy.
- Agent corrections still enter `ml_training_data` as active-learning signals for newer niche complaints and edge cases.
