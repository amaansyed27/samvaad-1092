import { useEffect, useRef } from 'react';

export default function TranscriptPanel({ events = [], scrubbed = '', piiCount = 0, partialTranscript = '' }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div className="glass-card flex flex-col h-full bg-black/20 border-white/5 shadow-2xl">
      {/* Header */}
      <div className="flex-none flex items-center justify-between px-6 py-4 border-b border-white/5 bg-white/[0.02]">
        <div className="flex items-center gap-3">
          <div className="relative flex h-2.5 w-2.5">
            {events.length > 0 && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>}
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500"></span>
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-white/60 drop-shadow-sm">
            Live Transcript
          </span>
        </div>
        {piiCount > 0 && (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-orange-500/10 border border-orange-500/20 shadow-[0_0_10px_rgba(249,115,22,0.1)]">
            <span className="text-orange-400 text-xs font-bold tracking-wider uppercase">
              🛡 {piiCount} PII Redacted
            </span>
          </div>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-8 py-6 space-y-4 custom-scrollbar bg-black/20">
        {partialTranscript && (
          <div className="p-4 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-100 animate-pulse">
            <span className="text-[9px] font-black uppercase tracking-widest text-indigo-300 block mb-1">
              Live Partial
            </span>
            <span className="text-sm font-medium">{partialTranscript}</span>
          </div>
        )}
        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-white/10">
             <div className="w-16 h-16 rounded-full border border-white/5 flex items-center justify-center animate-pulse">
               <span className="text-2xl">📡</span>
             </div>
             <span className="text-[10px] font-black uppercase tracking-[0.3em]">Monitoring Radio Waves</span>
          </div>
        ) : (
          events.map((ev, i) => (
            <div
              key={i}
              className={`group relative flex gap-6 items-start transition-all duration-500 animate-slide-up`}
              style={{ animationDelay: `${Math.min(i * 30, 300)}ms` }}
            >
              {/* Time indicator */}
              <div className="flex-none w-16 pt-1">
                <span className="text-[9px] font-mono text-white/20 font-bold tracking-tighter">
                  {new Date(ev.timestamp || Date.now()).toLocaleTimeString('en-IN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
              </div>
              
              {/* Content */}
              <div className={`flex-1 pb-4 border-l border-white/5 pl-6 group-last:border-transparent`}>
                <div className="text-[11px] leading-relaxed text-white/60 font-medium">
                  {formatEvent(ev)}
                </div>
              </div>
            </div>
          ))
        )}


        {/* Show scrubbed transcript if available */}
        {scrubbed && (
          <div className="mt-6 p-5 rounded-xl bg-indigo-500/5 border border-indigo-500/10 shadow-inner">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-indigo-400">🛡</span>
              <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-300">
                Scrubbed Transcript
              </span>
            </div>
            <p className="text-sm text-indigo-100/70 leading-relaxed font-medium">
              {scrubbed}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function formatEvent(ev) {
  switch (ev.event) {
    case 'state_change':
      return <span className="text-indigo-400/80 font-bold tracking-widest uppercase text-[9px]">→ {ev.state} ACTIVE</span>;
    case 'audio_processed':
      return <span className="text-white/40">ACOUSTIC PROFILING: <span className="text-white/80">{(ev.distress?.score * 100 || 0).toFixed(0)}% DISTRESS DETECTED</span></span>;
    case 'transcript_received':
      return <span className="text-white/90">"{ev.transcript}" <span className="text-white/20 uppercase text-[8px] ml-2">[{ev.language_code || '??'}]</span></span>;
    case 'partial_transcript':
      return <span className="text-indigo-200/80">PARTIAL: "{ev.transcript}" <span className="text-white/20 uppercase text-[8px] ml-2">[{ev.language_code || '??'}]</span></span>;
    case 'final_transcript':
      return <span className="text-white/90 font-semibold">FINAL: "{ev.transcript}" <span className="text-white/20 uppercase text-[8px] ml-2">[{ev.language_code || '??'}]</span></span>;
    case 'slot_update':
      return <span className="text-amber-200/80">SLOTS: {Object.entries(ev.slots || {}).map(([k, v]) => `${k}=${v}`).join(' | ')}</span>;
    case 'classification_update':
      return <span className="text-emerald-300/80">CLASSIFIED: {ev.department || 'UNKNOWN'} / {ev.emergency_type || 'other'} ({((ev.confidence || 0) * 100).toFixed(0)}%)</span>;
    case 'sentiment_update':
      return <span className="text-pink-300/80">SENTIMENT: {ev.sentiment || 'unknown'} ({((ev.confidence || 0) * 100).toFixed(0)}%)</span>;
    case 'clarification_required':
      return <span className="text-amber-300 font-medium">CLARIFICATION REQUIRED: "{ev.prompt}"</span>;
    case 'assistant_text':
      return <span className="text-sky-400 font-medium italic">ASSISTANT: "{ev.text}"</span>;
    case 'assistant_audio_chunk':
      return <span className="text-white/35">TTS AUDIO CHUNK: {ev.codec || 'audio'} / {ev.sample_rate || '--'} Hz</span>;
    case 'audio_activity':
      return <span className="text-cyan-300/70">AUDIO: {ev.source || 'mic'} {ev.status || 'activity'} {ev.rms ? `(rms ${ev.rms})` : ''}</span>;
    case 'stt_status':
      return <span className="text-cyan-200/70">STT: {ev.status || 'status'} {ev.buffered_bytes ? `(${ev.buffered_bytes} bytes)` : ''}</span>;
    case 'playback_cancel':
      return <span className="text-red-300/80">BARGE-IN: Assistant playback cancelled</span>;
    case 'latency_metrics':
      return <span className="text-white/50">LATENCY: {Object.entries(ev.metrics || {}).map(([k, v]) => `${k}=${Math.round(v)}ms`).join(' | ')}</span>;
    case 'ivr_menu':
      return <span className="text-amber-300 font-bold uppercase text-[9px] tracking-widest">IVR MENU: {ev.prompt}</span>;
    case 'language_selected':
      return <span className="text-emerald-300 font-bold uppercase text-[9px] tracking-widest">LANGUAGE LOCKED: {ev.language_code} {ev.language ? `(${ev.language})` : ''}</span>;
    case 'restatement':
      return <span className="text-sky-400 font-medium italic">AI RESTATEMENT: "{ev.restatement}"</span>;
    case 'VERIFIED':
      return (
        <div className="p-4 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
          <span className="font-black uppercase tracking-widest block mb-1">✓ CALL VERIFIED</span>
          <p className="text-[10px] opacity-80">{ev.dispatch_message}</p>
        </div>
      );
    case 'location_update':
      return <span className="text-amber-400 uppercase text-[9px] font-black">📍 GPS LOCK: {ev.location.city || 'UNCERTAIN'}</span>;

    case 'SAFE_HUMAN_TAKEOVER':
      return <span className="text-[#ef4444] font-bold">⚠ HUMAN TAKEOVER — {ev.reason}</span>;
    case 'error':
      return <span className="text-[#ef4444]">❌ {ev.message}</span>;
    default:
      return JSON.stringify(ev);
  }
}
