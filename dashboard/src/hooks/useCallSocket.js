import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * useCallSocket — React hook for WebSocket communication with the Samvaad 1092 backend.
 *
 * Manages connection lifecycle, message routing, and provides imperative methods
 * for sending audio, transcripts, confirmations, manual takeover, and agent edits.
 *
 * @param {string} url - WebSocket URL (defaults to /ws/call via Vite proxy)
 * @returns {object} Complete call state and control methods
 */
export function useCallSocket(url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/call`) {
  const [connected, setConnected] = useState(false);
  const [callId, setCallId] = useState(null);
  const [state, setState] = useState('INIT');
  const [events, setEvents] = useState([]);
  const [distress, setDistress] = useState({ score: 0, level: 'LOW', features: {} });
  const [analysis, setAnalysis] = useState(null);
  const [restatement, setRestatement] = useState('');
  const [ttsAudio, setTtsAudio] = useState('');
  const [confidence, setConfidence] = useState(0);
  const [piiCount, setPiiCount] = useState(0);
  const [liveTranscript, setLiveTranscript] = useState('');
  const [languageCode, setLanguageCode] = useState('unknown');
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const handleEvent = useCallback((data) => {
    setEvents((prev) => [...prev.slice(-99), data]); // keep last 100

    if (data.call_id) setCallId(data.call_id);

    switch (data.event) {
      case 'state_change':
        setState(data.state);
        if (data.pii_count !== undefined) setPiiCount(data.pii_count);
        if (data.confidence !== undefined) setConfidence(data.confidence);
        if (data.analysis) setAnalysis(data.analysis);
        break;

      case 'audio_processed':
        if (data.distress) setDistress(data.distress);
        break;

      case 'transcript_received':
        setLiveTranscript(data.transcript || '');
        if (data.language_code) setLanguageCode(data.language_code);
        break;

      case 'restatement':
        setState(data.state);
        setRestatement(data.restatement);
        if (data.tts_audio) {
          setTtsAudio(data.tts_audio);
          // Auto-play TTS audio
          playTtsAudio(data.tts_audio);
        }
        break;

      case 'VERIFIED':
        setState('VERIFIED');
        setConfidence(data.confidence);
        break;

      case 'SAFE_HUMAN_TAKEOVER':
        setState('HUMAN_TAKEOVER');
        setDistress((prev) => ({ ...prev, score: data.distress_score || prev.score, level: 'CRITICAL' }));
        break;

      case 'agent_edit_saved':
        // Update local analysis with corrections
        if (data.corrections && analysis) {
          setAnalysis(prev => ({ ...prev, ...data.corrections }));
        }
        break;

      default:
        break;
    }
  }, [analysis]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) return;

    // Small delay to bypass React Strict Mode instant unmounts
    const timerId = setTimeout(() => {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        console.log('[Samvaad WS] Connected');
      };

      ws.onclose = () => {
        setConnected(false);
        console.log('[Samvaad WS] Disconnected — reconnecting in 3s');
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.error('[Samvaad WS] Error:', err);
      };

      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          handleEvent(data);
        } catch (e) {
          console.warn('[Samvaad WS] Invalid message:', msg.data);
        }
      };
    }, 50);
    
    // Store timer so it can be cleared on unmount
    wsRef.current = { isPending: true, timerId, close: () => clearTimeout(timerId) };
  }, [url, handleEvent]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  // ── Send helpers ──────────────────────────────────────────────────────

  const send = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const sendTranscript = useCallback((text) => {
    send({ type: 'transcript', text });
  }, [send]);

  const sendConfirm = useCallback((confirmed) => {
    send({ type: 'confirm', confirmed });
  }, [send]);

  const sendAudio = useCallback((base64Data) => {
    send({ type: 'audio', data: base64Data });
  }, [send]);

  const sendTakeover = useCallback((reason = 'Agent initiated manual takeover') => {
    send({ type: 'takeover', reason });
  }, [send]);

  const sendAgentEdit = useCallback((corrections) => {
    send({ type: 'agent_edit', corrections });
  }, [send]);

  return {
    connected,
    callId,
    state,
    events,
    distress,
    analysis,
    restatement,
    ttsAudio,
    confidence,
    piiCount,
    liveTranscript,
    languageCode,
    send,
    sendTranscript,
    sendConfirm,
    sendAudio,
    sendTakeover,
    sendAgentEdit,
  };
}


// ── TTS Audio Playback ────────────────────────────────────────────────────

function playTtsAudio(base64Audio) {
  if (!base64Audio) return;
  try {
    const byteChars = atob(base64Audio);
    const byteArray = new Uint8Array(byteChars.length);
    for (let i = 0; i < byteChars.length; i++) {
      byteArray[i] = byteChars.charCodeAt(i);
    }
    const blob = new Blob([byteArray], { type: 'audio/wav' });
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    audio.play().catch(err => {
      console.warn('[TTS] Autoplay blocked:', err.message);
    });
    audio.addEventListener('ended', () => URL.revokeObjectURL(audioUrl));
  } catch (e) {
    console.error('[TTS] Playback error:', e);
  }
}
