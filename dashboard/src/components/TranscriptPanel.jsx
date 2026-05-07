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
      <div className="flex-none flex items-center justify-between px-6 py-4 border-b border-white/5 bg-white/[0.02]">
        <div className="flex items-center gap-3">
          <div className="relative flex h-2.5 w-2.5">
            {events.length > 0 && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />}
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500" />
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-white/60 drop-shadow-sm">
            Live Transcript
          </span>
        </div>
        {piiCount > 0 && (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-orange-500/10 border border-orange-500/20 shadow-[0_0_10px_rgba(249,115,22,0.1)]">
            <span className="text-orange-400 text-xs font-bold tracking-wider uppercase">
              {piiCount} PII Redacted
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
              <span className="text-2xl">...</span>
            </div>
            <span className="text-[10px] font-black uppercase tracking-[0.3em]">Waiting For Caller</span>
          </div>
        ) : (
          events.map((ev, i) => (
            <div
              key={i}
              className="group relative flex gap-6 items-start transition-all duration-500 animate-slide-up"
              style={{ animationDelay: `${Math.min(i * 30, 300)}ms` }}
            >
              <div className="flex-none w-16 pt-1">
                <span className="text-[9px] font-mono text-white/20 font-bold tracking-tighter">
                  {new Date(ev.timestamp || Date.now()).toLocaleTimeString('en-IN', {
                    hour12: false,
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
              </div>

              <div className="flex-1 pb-4 border-l border-white/5 pl-6 group-last:border-transparent">
                <div className="text-[11px] leading-relaxed text-white/60 font-medium">
                  {formatEvent(ev)}
                </div>
              </div>
            </div>
          ))
        )}

        {scrubbed && (
          <div className="mt-6 p-5 rounded-xl bg-indigo-500/5 border border-indigo-500/10 shadow-inner">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-300">
                Scrubbed Transcript
              </span>
            </div>
            <p className="text-sm text-indigo-100/70 leading-relaxed font-medium">{scrubbed}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function formatEvent(ev) {
  switch (ev.event) {
    case 'state_change':
      return <span className="text-indigo-400/80 font-bold tracking-widest uppercase text-[9px]">{ev.state} active</span>;
    case 'audio_processed':
      return <DistressLog distress={ev.distress} />;
    case 'transcript_received':
      return <TranscriptLog label="Transcript" text={ev.transcript} language={ev.language_code} />;
    case 'partial_transcript':
      return <TranscriptLog label="Partial" text={ev.transcript} language={ev.language_code} muted />;
    case 'final_transcript':
      return <TranscriptLog label="Final" text={ev.transcript} language={ev.language_code} strong />;
    case 'slot_update':
      return <SlotLog slots={ev.slots || {}} />;
    case 'classification_update':
      return <ClassificationLog ev={ev} />;
    case 'sentiment_update':
      return <span className="text-pink-300/80">Caller tone: {ev.sentiment || 'unknown'} ({percent(ev.confidence)} confidence)</span>;
    case 'abuse_guardrail':
      return <AbuseLog ev={ev} />;
    case 'location_resolution':
      return <LocationResolutionLog ev={ev} />;
    case 'clarification_required':
      return <span className="text-amber-300 font-medium">Needs caller detail: "{ev.prompt}"</span>;
    case 'assistant_text':
      return <span className="text-sky-400 font-medium italic">Assistant: "{ev.text}"</span>;
    case 'assistant_audio_chunk':
      return <span className="text-white/35">Assistant audio started: {ev.codec || 'audio'} / {ev.sample_rate || '--'} Hz</span>;
    case 'audio_activity':
      return <span className="text-cyan-300/70">Audio: {ev.source || 'mic'} {ev.status || 'activity'} {ev.rms ? `(rms ${ev.rms})` : ''}</span>;
    case 'stt_status':
      return <span className="text-cyan-200/70">STT: {cleanStatus(ev.status)} {ev.buffered_bytes ? `(${ev.buffered_bytes} bytes)` : ''}</span>;
    case 'playback_cancel':
      return <span className="text-red-300/80">Caller interrupted: assistant playback cancelled</span>;
    case 'latency_metrics':
      return <span className="text-white/50">Latency: {Object.entries(ev.metrics || {}).map(([k, v]) => `${k}=${Math.round(v)}ms`).join(' | ')}</span>;
    case 'ivr_menu':
      return <span className="text-amber-300 font-bold uppercase text-[9px] tracking-widest">IVR menu: {ev.prompt}</span>;
    case 'language_selected':
      return <span className="text-emerald-300 font-bold uppercase text-[9px] tracking-widest">Language locked: {ev.language_code} {ev.language ? `(${ev.language})` : ''}</span>;
    case 'restatement':
      return <span className="text-sky-400 font-medium italic">AI restatement: "{ev.restatement}"</span>;
    case 'VERIFIED':
      return (
        <div className="p-4 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
          <span className="font-black uppercase tracking-widest block mb-1">Call verified</span>
          <p className="text-[10px] opacity-80">{ev.dispatch_message}</p>
        </div>
      );
    case 'location_update':
      return <span className="text-amber-400 uppercase text-[9px] font-black">GPS: {ev.location?.city || 'uncertain'}</span>;
    case 'SAFE_HUMAN_TAKEOVER':
      return <span className="text-[#ef4444] font-bold">Human takeover: {ev.reason}</span>;
    case 'error':
      return <span className="text-[#ef4444]">{ev.message}</span>;
    default:
      return JSON.stringify(ev);
  }
}

function DistressLog({ distress = {} }) {
  const score = Number(distress.score || 0);
  const band = score >= 0.75 ? 'high' : score >= 0.45 ? 'elevated' : 'low';
  const color = band === 'high' ? 'text-red-300' : band === 'elevated' ? 'text-amber-300' : 'text-emerald-300';
  const note = band === 'high'
    ? 'Use calm reassurance; consider human support.'
    : band === 'elevated'
      ? 'Caller may be stressed; acknowledge before asking.'
      : 'Caller appears calm; continue normal intake.';

  return (
    <div className="space-y-1">
      <div className={color}>Distress classification: {percent(score)} ({band})</div>
      <div className="text-[10px] text-white/35">{note}</div>
    </div>
  );
}

function ClassificationLog({ ev }) {
  return (
    <div className="space-y-1">
      <div className="text-emerald-300/80">
        Classified: {ev.department || 'UNKNOWN'} / {ev.emergency_type || 'other'} ({percent(ev.confidence)})
      </div>
      {(ev.priority || ev.severity) && (
        <div className="text-[10px] text-white/45">
          Priority {ev.priority || '--'} / severity {ev.severity || '--'}{ev.priority_reason ? ` - ${ev.priority_reason}` : ''}
        </div>
      )}
      {ev.empathy_note && <div className="text-[10px] text-sky-300/70">Empathy cue: {ev.empathy_note}</div>}
    </div>
  );
}

function LocationResolutionLog({ ev }) {
  const candidates = ev.candidates || (ev.candidate ? [ev.candidate] : []);
  const top = candidates[0];
  return (
    <div className="space-y-1">
      <div className="text-emerald-300/90">
        Location check: {ev.status || 'candidate'}{ev.source ? ` via ${ev.source}` : ''}
      </div>
      {ev.reason && <div className="text-[10px] text-white/40">{ev.reason}</div>}
      {top?.name && (
        <div className="text-[10px] text-amber-200/80">
          Candidate: {top.name} ({percent(top.confidence)})
        </div>
      )}
    </div>
  );
}

function AbuseLog({ ev }) {
  return (
    <div className="p-3 rounded bg-red-500/10 border border-red-500/20 text-red-200">
      <span className="block text-[10px] font-black uppercase tracking-widest text-red-300">
        Abuse/spam guardrail: {ev.action} ({percent(ev.score)})
      </span>
      <span className="text-[10px] text-red-200/80">{ev.reason || 'Review before ticketing or blacklist action.'}</span>
    </div>
  );
}

function TranscriptLog({ label, text, language, muted, strong }) {
  const cls = muted ? 'text-indigo-200/80' : strong ? 'text-white/90 font-semibold' : 'text-white/90';
  return (
    <span className={cls}>
      {label}: "{text}" <span className="text-white/20 uppercase text-[8px] ml-2">[{language || '??'}]</span>
    </span>
  );
}

function SlotLog({ slots }) {
  const rows = [
    ['issue', slots.issue],
    ['dept', slots.department],
    ['area', slots.area],
    ['landmark', slots.landmark],
    ['loc_check', slots.location_validation_status],
    ['loc_conf', Number.isFinite(slots.location_confidence) ? `${Math.round(slots.location_confidence * 100)}%` : ''],
    ['priority', slots.urgency],
    ['next', slots.required_slot],
  ].filter(([, value]) => value !== undefined && value !== null && value !== '');

  return <span className="text-amber-200/80">Slots: {rows.map(([k, v]) => `${k}=${v}`).join(' | ')}</span>;
}

function cleanStatus(status = 'status') {
  return status.replaceAll('_', ' ');
}

function percent(value) {
  return `${(Number(value || 0) * 100).toFixed(0)}%`;
}
