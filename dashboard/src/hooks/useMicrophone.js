import { useState, useRef, useCallback, useEffect } from 'react';

function encodeWAV(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset, string) => {
    for (let i = 0; i < string.length; i++) view.setUint8(offset + i, string.charCodeAt(i));
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([view], { type: 'audio/wav' });
}

function floatToPcm16Base64(samples) {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function rms(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / Math.max(samples.length, 1));
}

const SPEECH_RMS_THRESHOLD = 0.0025;
const SILENCE_RMS_THRESHOLD = 0.0018;

export function useMicrophone({
  onAudioFrame,
  onAudioEnd,
  onAudioChunk,
  chunkIntervalMs = 3000,
  sampleRate = 16000,
} = {}) {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState(null);

  const streamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);
  const animFrameRef = useRef(null);
  const wavBufferRef = useRef([]);
  const intervalRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const speechActiveRef = useRef(false);

  const updateLevel = useCallback(() => {
    if (!analyserRef.current) return;
    const data = new Uint8Array(analyserRef.current.frequencyBinCount);
    analyserRef.current.getByteFrequencyData(data);
    const avg = data.reduce((sum, v) => sum + v, 0) / data.length;
    setAudioLevel(avg / 255);
    animFrameRef.current = requestAnimationFrame(updateLevel);
  }, []);

  const emitWavFallback = useCallback(() => {
    if (!onAudioChunk || !wavBufferRef.current.length) return;
    const totalLen = wavBufferRef.current.reduce((acc, curr) => acc + curr.length, 0);
    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const arr of wavBufferRef.current) {
      merged.set(arr, offset);
      offset += arr.length;
    }
    wavBufferRef.current = [];
    if (rms(merged) < SILENCE_RMS_THRESHOLD) return;

    const wavBlob = encodeWAV(merged, sampleRate);
    const reader = new FileReader();
    reader.onloadend = () => {
      if (reader.result) onAudioChunk(reader.result.split(',')[1]);
    };
    reader.readAsDataURL(wavBlob);
  }, [onAudioChunk, sampleRate]);

  const markSpeechEndSoon = useCallback(() => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = setTimeout(() => {
      if (speechActiveRef.current) {
        speechActiveRef.current = false;
        onAudioEnd?.(sampleRate);
      }
    }, 650);
  }, [onAudioEnd, sampleRate]);

  const startRecording = useCallback(async () => {
    try {
      setError(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate, echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;

      const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate });
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;
      updateLevel();

      const processor = audioCtx.createScriptProcessor(2048, 1, 1);
      processorRef.current = processor;
      wavBufferRef.current = [];

      processor.onaudioprocess = (e) => {
        const inputData = new Float32Array(e.inputBuffer.getChannelData(0));
        wavBufferRef.current.push(inputData);
        const level = rms(inputData);

        if (level < SPEECH_RMS_THRESHOLD) {
          markSpeechEndSoon();
          return;
        }

        speechActiveRef.current = true;
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        onAudioFrame?.(floatToPcm16Base64(inputData), sampleRate);
      };

      source.connect(analyser);
      analyser.connect(processor);
      processor.connect(audioCtx.destination);

      if (onAudioChunk) {
        intervalRef.current = setInterval(emitWavFallback, chunkIntervalMs);
      }

      setIsRecording(true);
    } catch (err) {
      setError(err.message);
      console.error('[Microphone] Failed to start:', err);
    }
  }, [chunkIntervalMs, emitWavFallback, markSpeechEndSoon, onAudioChunk, onAudioFrame, sampleRate, updateLevel]);

  const stopRecording = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    if (processorRef.current) processorRef.current.disconnect();
    if (audioCtxRef.current) audioCtxRef.current.close();
    if (streamRef.current) streamRef.current.getTracks().forEach((track) => track.stop());
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    if (speechActiveRef.current) onAudioEnd?.(sampleRate);
    emitWavFallback();

    speechActiveRef.current = false;
    setIsRecording(false);
    setAudioLevel(0);
  }, [emitWavFallback, onAudioEnd, sampleRate]);

  useEffect(() => () => stopRecording(), [stopRecording]);

  return {
    isRecording,
    audioLevel,
    error,
    startRecording,
    stopRecording,
  };
}
