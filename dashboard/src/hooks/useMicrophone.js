import { useState, useRef, useCallback, useEffect } from 'react';

/**
 * Encodes PCM array data into a WAV blob
 */
function encodeWAV(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  
  const writeString = (view, offset, string) => {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };
  
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // Mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, 'data');
  view.setUint32(40, samples.length * 2, true);
  
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return new Blob([view], { type: 'audio/wav' });
}

/**
 * useMicrophone — React hook for browser microphone capture.
 *
 * Captures raw PCM using AudioContext/ScriptProcessorNode and encodes to WAV.
 * This guarantees the backend soundfile parser can read the bytes correctly.
 *
 * @param {object} options
 * @param {function} options.onAudioChunk - Callback receiving base64 audio data
 * @param {number} options.chunkIntervalMs - Interval between chunks (default: 3000ms)
 */
export function useMicrophone({ onAudioChunk, chunkIntervalMs = 3000 } = {}) {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState(null);

  const streamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const processorRef = useRef(null);
  const pcmDataRef = useRef([]);
  const intervalRef = useRef(null);
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
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;

      const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;
      updateLevel();

      // We use ScriptProcessorNode because MediaRecorder doesn't natively produce WAV in browsers
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      
      pcmDataRef.current = [];
      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        pcmDataRef.current.push(new Float32Array(inputData));
      };

      source.connect(analyser);
      analyser.connect(processor);
      processor.connect(audioCtx.destination); // required for script processor to fire

      intervalRef.current = setInterval(() => {
        if (!pcmDataRef.current.length) return;
        
        // Merge all PCM arrays into one
        const totalLen = pcmDataRef.current.reduce((acc, curr) => acc + curr.length, 0);
        const merged = new Float32Array(totalLen);
        let offset = 0;
        let sumSquares = 0;
        for (let arr of pcmDataRef.current) {
          merged.set(arr, offset);
          for (let i = 0; i < arr.length; i++) {
            sumSquares += arr[i] * arr[i];
          }
          offset += arr.length;
        }
        pcmDataRef.current = [];

        // RMS silence detection - filter out chunks that are purely background noise
        const rms = Math.sqrt(sumSquares / totalLen);
        if (rms < 0.005) {
          // Chunk is too quiet, skip sending it to save API calls and prevent STT hallucinations
          console.log('[Microphone] Chunk rejected (silence). RMS:', rms.toFixed(5));
          return;
        }

        // Encode to WAV and send as Base64
        const wavBlob = encodeWAV(merged, 16000);
        const reader = new FileReader();
        reader.onloadend = () => {
          if (onAudioChunk && reader.result) {
            onAudioChunk(reader.result.split(',')[1]); // strip data:audio/wav;base64,
          }
        };
        reader.readAsDataURL(wavBlob);
      }, chunkIntervalMs);

      setIsRecording(true);
    } catch (err) {
      setError(err.message);
      console.error('[Microphone] Failed to start:', err);
    }
  }, [onAudioChunk, chunkIntervalMs, updateLevel]);

  const stopRecording = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (processorRef.current) processorRef.current.disconnect();
    if (audioCtxRef.current) audioCtxRef.current.close();
    if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    
    setIsRecording(false);
    setAudioLevel(0);
  }, []);

  useEffect(() => {
    return () => stopRecording();
  }, [stopRecording]);

  return {
    isRecording,
    audioLevel,
    error,
    startRecording,
    stopRecording,
  };
}
