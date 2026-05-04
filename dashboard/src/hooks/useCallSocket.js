import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * useCallSocket — React hook for WebSocket communication with the Samvaad 1092 backend.
 *
 * Manages connection lifecycle, message routing, and provides imperative methods
 * for sending audio, transcripts, and confirmations.
 *
 * @param {string} url - WebSocket URL (defaults to /ws/call via Vite proxy)
 * @returns {object} { state, events, distress, analysis, restatement, send, sendTranscript, sendConfirm, connected }
 */
export function useCallSocket(url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/call`) {
  const [connected, setConnected] = useState(false);
  const [callId, setCallId] = useState(null);
  const [state, setState] = useState('INIT');
  const [events, setEvents] = useState([]);
  const [distress, setDistress] = useState({ score: 0, level: 'LOW', features: {} });
  const [analysis, setAnalysis] = useState(null);
  const [restatement, setRestatement] = useState('');
  const [confidence, setConfidence] = useState(0);
  const [piiCount, setPiiCount] = useState(0);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

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
  }, [url]);

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

      case 'restatement':
        setState(data.state);
        setRestatement(data.restatement);
        break;

      case 'VERIFIED':
        setState('VERIFIED');
        setConfidence(data.confidence);
        break;

      case 'SAFE_HUMAN_TAKEOVER':
        setState('HUMAN_TAKEOVER');
        setDistress((prev) => ({ ...prev, score: data.distress_score || prev.score, level: 'CRITICAL' }));
        break;

      default:
        break;
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

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

  return {
    connected,
    callId,
    state,
    events,
    distress,
    analysis,
    restatement,
    confidence,
    piiCount,
    send,
    sendTranscript,
    sendConfirm,
  };
}
