import { useState, useEffect, useRef, useCallback } from 'react';

const DEFAULT_WS_URL = import.meta.env.VITE_WS_URL
  || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/call`;
const DASHBOARD_WS_URL = import.meta.env.VITE_DASHBOARD_WS_URL
  || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/dashboard`;

export function useCallSocket(url = DEFAULT_WS_URL) {
  const [connected, setConnected] = useState(false);
  const [callId, setCallId] = useState(null);
  const [state, setState] = useState('INIT');
  const [events, setEvents] = useState([]);
  const [distress, setDistress] = useState({ score: 0, level: 'LOW', features: {} });
  const [analysis, setAnalysis] = useState(null);
  const [restatement, setRestatement] = useState('');
  const [assistantText, setAssistantText] = useState('');
  const [ttsAudio, setTtsAudio] = useState('');
  const [confidence, setConfidence] = useState(0);
  const [piiCount, setPiiCount] = useState(0);
  const [liveTranscript, setLiveTranscript] = useState('');
  const [partialTranscript, setPartialTranscript] = useState('');
  const [languageCode, setLanguageCode] = useState('unknown');
  const [selectedLanguage, setSelectedLanguage] = useState('unknown');
  const [location, setLocation] = useState(null);
  const [mlRouting, setMlRouting] = useState(null);
  const [slots, setSlots] = useState({});
  const [conversationMemory, setConversationMemory] = useState({});
  const [conversationTurns, setConversationTurns] = useState([]);
  const [latencyMetrics, setLatencyMetrics] = useState({});
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);

  const wsRef = useRef(null);
  const dashboardWsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const dashboardReconnectTimer = useRef(null);
  const callIdRef = useRef(null);
  const audioCtxRef = useRef(null);
  const nextAudioTimeRef = useRef(0);
  const activeSourcesRef = useRef([]);

  const stopPlayback = useCallback(() => {
    activeSourcesRef.current.forEach((source) => {
      try { source.stop(); } catch (_) { /* already stopped */ }
    });
    activeSourcesRef.current = [];
    nextAudioTimeRef.current = 0;
    setIsAssistantSpeaking(false);
  }, []);

  const handleEvent = useCallback((data) => {
    setEvents((prev) => [...prev.slice(-99), data]);

    if (data.call_id) {
      setCallId(data.call_id);
      callIdRef.current = data.call_id;
    }

    switch (data.event) {
      case 'state_change':
        setState(data.state);
        if (data.pii_count !== undefined) setPiiCount(data.pii_count);
        if (data.confidence !== undefined) setConfidence(data.confidence);
        if (data.analysis) setAnalysis(data.analysis);
        if (data.slots) setSlots(data.slots);
        if (data.conversation_memory) setConversationMemory(data.conversation_memory);
        break;

      case 'audio_processed':
        if (data.distress) setDistress(data.distress);
        break;

      case 'partial_transcript':
        setPartialTranscript(data.transcript || '');
        if (data.transcript) setLiveTranscript(data.transcript);
        if (data.language_code) setLanguageCode(data.language_code);
        break;

      case 'final_transcript':
      case 'transcript_received':
        setPartialTranscript('');
        setLiveTranscript(data.transcript || '');
        if (data.language_code) setLanguageCode(data.language_code);
        if (data.ml_routing) setMlRouting(data.ml_routing);
        break;

      case 'language_selected':
        if (data.language_code) {
          setSelectedLanguage(data.language_code);
          setLanguageCode(data.language_code);
        }
        break;

      case 'ml_routing_update':
        setMlRouting(data.ml_routing);
        break;

      case 'classification_update':
        if (data.analysis) setAnalysis(data.analysis);
        if (data.confidence !== undefined) setConfidence(data.confidence);
        break;

      case 'sentiment_update':
        setAnalysis((prev) => ({ ...(prev || {}), sentiment: data.sentiment }));
        break;

      case 'slot_update':
        setSlots(data.slots || {});
        break;

      case 'conversation_memory_update':
        if (data.conversation_memory) setConversationMemory(data.conversation_memory);
        if (data.slots) setSlots(data.slots || {});
        break;

      case 'conversation_turn':
        if (data.turn) {
          setConversationTurns((prev) => {
            const last = prev[prev.length - 1];
            if (last?.text === data.turn.text && last?.role === data.turn.role && last?.timestamp === data.turn.timestamp) {
              return prev;
            }
            const next = [...prev, data.turn];
            return next.slice(-80);
          });
        }
        if (data.conversation_memory) setConversationMemory(data.conversation_memory);
        break;

      case 'restatement':
        setState(data.state);
        setRestatement(data.restatement);
        if (data.slots) setSlots(data.slots);
        if (data.tts_audio) {
          setTtsAudio(data.tts_audio);
          playWavAudio(data.tts_audio);
        }
        break;

      case 'clarification_required':
        if (data.prompt) setRestatement(data.prompt);
        if (data.slots) setSlots(data.slots);
        break;

      case 'assistant_text':
        setAssistantText(data.text || '');
        if (data.text) setRestatement(data.text);
        break;

      case 'assistant_audio_chunk':
        setIsAssistantSpeaking(true);
        playAssistantChunk(data, audioCtxRef, nextAudioTimeRef, activeSourcesRef, () => {
          setIsAssistantSpeaking(false);
        });
        break;

      case 'playback_cancel':
        stopPlayback();
        break;

      case 'latency_metrics':
        setLatencyMetrics(data.metrics || {});
        setIsAssistantSpeaking(false);
        break;

      case 'VERIFIED':
        setState('VERIFIED');
        setConfidence(data.confidence);
        if (data.slots) setSlots(data.slots);
        if (data.conversation_memory) setConversationMemory(data.conversation_memory);
        if (data.dispatch_message) setAssistantText(data.dispatch_message);
        if (data.tts_audio) playWavAudio(data.tts_audio);
        break;

      case 'location_update':
        setLocation(data.location);
        break;

      case 'SAFE_HUMAN_TAKEOVER':
        setState('HUMAN_TAKEOVER');
        setDistress((prev) => ({ ...prev, score: data.distress_score || prev.score, level: 'CRITICAL' }));
        break;

      case 'agent_edit_saved':
        if (data.corrections) setAnalysis((prev) => ({ ...(prev || {}), ...data.corrections }));
        break;

      default:
        break;
    }
  }, [stopPlayback]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) return;

    const timerId = setTimeout(() => {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        console.log('[Samvaad WS] Connected');
      };

      ws.onclose = () => {
        setConnected(false);
        console.log('[Samvaad WS] Disconnected - reconnecting in 3s');
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.error('[Samvaad WS] Error:', err);
      };

      ws.onmessage = (msg) => {
        try {
          handleEvent(JSON.parse(msg.data));
        } catch (_) {
          console.warn('[Samvaad WS] Invalid message:', msg.data);
        }
      };
    }, 50);

    wsRef.current = { isPending: true, timerId, close: () => clearTimeout(timerId) };
  }, [url, handleEvent]);

  const connectDashboard = useCallback(() => {
    if (dashboardWsRef.current?.readyState === WebSocket.OPEN || dashboardWsRef.current?.readyState === WebSocket.CONNECTING) return;

    const ws = new WebSocket(DASHBOARD_WS_URL);
    dashboardWsRef.current = ws;
    ws.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data);
        handleEvent(event);
      } catch (_) {
        console.warn('[Samvaad Dashboard WS] Invalid message:', msg.data);
      }
    };
    ws.onclose = () => {
      dashboardReconnectTimer.current = setTimeout(connectDashboard, 3000);
    };
    ws.onerror = (err) => {
      console.error('[Samvaad Dashboard WS] Error:', err);
    };
  }, [handleEvent]);

  useEffect(() => {
    connect();
    connectDashboard();
    return () => {
      clearTimeout(reconnectTimer.current);
      clearTimeout(dashboardReconnectTimer.current);
      stopPlayback();
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
      if (dashboardWsRef.current) {
        dashboardWsRef.current.onclose = null;
        dashboardWsRef.current.close();
      }
      audioCtxRef.current?.close?.();
    };
  }, [connect, connectDashboard, stopPlayback]);

  const send = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const payload = { ...data };
      if (callIdRef.current && !payload.call_id) payload.call_id = callIdRef.current;
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const sendTranscript = useCallback((text) => send({ type: 'transcript', text }), [send]);
  const sendConfirm = useCallback((confirmed) => send({ type: 'confirm', confirmed }), [send]);
  const sendAudio = useCallback((base64Data) => send({ type: 'audio', data: base64Data }), [send]);
  const sendAudioFrame = useCallback((base64Data, sampleRate = 16000) => {
    send({ type: 'audio_frame', data: base64Data, sample_rate: sampleRate });
  }, [send]);
  const sendAudioEnd = useCallback((sampleRate = 16000) => {
    send({ type: 'audio_end', sample_rate: sampleRate });
  }, [send]);
  const sendLanguageSelect = useCallback((languageCode) => {
    send({ type: 'language_select', language_code: languageCode });
  }, [send]);
  const sendTakeover = useCallback((reason = 'Agent initiated manual takeover') => {
    send({ type: 'takeover', reason });
  }, [send]);
  const sendAgentEdit = useCallback((corrections) => {
    send({ type: 'agent_edit', corrections });
  }, [send]);
  const sendCorrection = useCallback((corrections) => {
    send({ type: 'correction', corrections, feedback_type: 'partial_correct' });
  }, [send]);

  return {
    connected,
    callId,
    state,
    events,
    distress,
    analysis,
    restatement,
    assistantText,
    ttsAudio,
    confidence,
    piiCount,
    liveTranscript,
    partialTranscript,
    languageCode,
    selectedLanguage,
    location,
    mlRouting,
    slots,
    conversationMemory,
    conversationTurns,
    latencyMetrics,
    isAssistantSpeaking,

    send,
    sendTranscript,
    sendConfirm,
    sendAudio,
    sendAudioFrame,
    sendAudioEnd,
    sendLanguageSelect,
    sendTakeover,
    sendAgentEdit,
    sendCorrection,
  };
}

function playAssistantChunk(data, audioCtxRef, nextAudioTimeRef, activeSourcesRef, onEnded) {
  if (!data.audio) return;
  const codec = data.codec || 'wav';
  const contentType = data.content_type || '';
  if (codec === 'wav' || contentType.includes('wav')) {
    playWavAudio(data.audio, onEnded);
    return;
  }
  if (codec !== 'pcm') return;

  const audioCtx = getAudioContext(audioCtxRef, data.sample_rate || 24000);
  const bytes = base64ToBytes(data.audio);
  const frameCount = Math.floor(bytes.length / 2);
  const buffer = audioCtx.createBuffer(1, frameCount, data.sample_rate || 24000);
  const channel = buffer.getChannelData(0);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let i = 0; i < frameCount; i++) {
    channel[i] = view.getInt16(i * 2, true) / 32768;
  }

  const source = audioCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(audioCtx.destination);
  const startAt = Math.max(audioCtx.currentTime + 0.02, nextAudioTimeRef.current || 0);
  nextAudioTimeRef.current = startAt + buffer.duration;
  activeSourcesRef.current.push(source);
  source.onended = () => {
    activeSourcesRef.current = activeSourcesRef.current.filter((item) => item !== source);
    if (activeSourcesRef.current.length === 0) onEnded?.();
  };
  source.start(startAt);
}

function getAudioContext(audioCtxRef, sampleRate) {
  if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
    audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)({ sampleRate });
  }
  if (audioCtxRef.current.state === 'suspended') audioCtxRef.current.resume();
  return audioCtxRef.current;
}

function base64ToBytes(base64Audio) {
  const byteChars = atob(base64Audio);
  const byteArray = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) byteArray[i] = byteChars.charCodeAt(i);
  return byteArray;
}

function playWavAudio(base64Audio, onEnded) {
  if (!base64Audio) return;
  try {
    const blob = new Blob([base64ToBytes(base64Audio)], { type: 'audio/wav' });
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    audio.play().catch((err) => {
      console.warn('[TTS] Autoplay blocked:', err.message);
    });
    audio.addEventListener('ended', () => {
      URL.revokeObjectURL(audioUrl);
      onEnded?.();
    });
  } catch (e) {
    console.error('[TTS] Playback error:', e);
  }
}
