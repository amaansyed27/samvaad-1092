import { useState, useRef, useCallback, useEffect } from 'react';

/**
 * useMicrophone — React hook for browser microphone capture.
 *
 * Captures audio from the user's microphone using the MediaRecorder API
 * and provides base64-encoded audio chunks for streaming to the backend.
 *
 * @param {object} options
 * @param {function} options.onAudioChunk - Callback receiving base64 audio data
 * @param {number} options.chunkIntervalMs - Interval between chunks (default: 3000ms)
 * @returns {object} { isRecording, startRecording, stopRecording, audioLevel }
 */
export function useMicrophone({ onAudioChunk, chunkIntervalMs = 3000 } = {}) {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState(null);

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const analyserRef = useRef(null);
  const animFrameRef = useRef(null);

  // Audio level visualiser
  const updateLevel = useCallback(() => {
    if (!analyserRef.current) return;
    const data = new Uint8Array(analyserRef.current.frequencyBinCount);
    analyserRef.current.getByteFrequencyData(data);
    const avg = data.reduce((sum, v) => sum + v, 0) / data.length;
    setAudioLevel(avg / 255); // Normalise to 0-1
    animFrameRef.current = requestAnimationFrame(updateLevel);
  }, []);

  const startRecording = useCallback(async () => {
    try {
      setError(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      // Set up audio analyser for level visualisation
      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;
      updateLevel();

      // Use MediaRecorder for chunked recording
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = async (e) => {
        if (e.data.size > 0 && onAudioChunk) {
          const buffer = await e.data.arrayBuffer();
          const base64 = btoa(
            new Uint8Array(buffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
          );
          onAudioChunk(base64);
        }
      };

      recorder.start(chunkIntervalMs);
      setIsRecording(true);
    } catch (err) {
      setError(err.message);
      console.error('[Microphone] Failed to start:', err);
    }
  }, [onAudioChunk, chunkIntervalMs, updateLevel]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
    }
    setIsRecording(false);
    setAudioLevel(0);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopRecording();
    };
  }, [stopRecording]);

  return {
    isRecording,
    audioLevel,
    error,
    startRecording,
    stopRecording,
  };
}
