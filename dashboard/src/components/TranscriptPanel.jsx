import { useEffect, useRef } from 'react';

/**
 * TranscriptPanel — Real-time scrolling transcript with PII highlighting.
 *
 * Displays a live feed of events from the verification pipeline, styled
 * as a minimal monochrome log with glassmorphism.
 */
export default function TranscriptPanel({ events = [], scrubbed = '', piiCount = 0 }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div className="glass-card flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-glass-border)]">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[var(--color-listening)]" style={{ animation: events.length > 0 ? 'pulse-dot 2s infinite' : 'none' }} />
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
            Live Transcript
          </span>
        </div>
        {piiCount > 0 && (
          <span className="status-badge" style={{ background: 'rgba(245, 165, 36, 0.12)', color: 'var(--color-warning)' }}>
            🛡 {piiCount} PII Redacted
          </span>
        )}
      </div>

      {/* Scrollable log */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-1" style={{ maxHeight: '360px' }}>
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full text-[var(--color-text-muted)] text-sm">
            Waiting for call connection…
          </div>
        ) : (
          events.map((ev, i) => (
            <div
              key={i}
              className={`transcript-line text-xs font-mono animate-slide-up ${
                ev.event === 'SAFE_HUMAN_TAKEOVER' ? 'border-l-[var(--color-critical)]' :
                ev.event === 'VERIFIED' ? 'border-l-[var(--color-verified)]' : ''
              }`}
              style={{
                animationDelay: `${Math.min(i * 30, 300)}ms`,
                borderLeftColor:
                  ev.event === 'SAFE_HUMAN_TAKEOVER' ? 'var(--color-critical)' :
                  ev.event === 'VERIFIED' ? 'var(--color-verified)' : undefined,
              }}
            >
              <span className="text-[var(--color-text-muted)] mr-2">
                {new Date(ev.timestamp || Date.now()).toLocaleTimeString('en-IN', { hour12: false })}
              </span>
              <span className="text-[var(--color-text-secondary)]">
                {formatEvent(ev)}
              </span>
            </div>
          ))
        )}

        {/* Show scrubbed transcript if available */}
        {scrubbed && (
          <div className="mt-3 p-3 rounded-lg bg-[rgba(255,255,255,0.02)] border border-[var(--color-glass-border)]">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">
              Scrubbed Transcript
            </div>
            <p className="text-xs text-[var(--color-text-primary)] leading-relaxed">
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
      return `→ ${ev.state}${ev.pii_count ? ` (${ev.pii_count} PII scrubbed)` : ''}`;
    case 'audio_processed':
      return `♪ Distress: ${(ev.distress?.score * 100 || 0).toFixed(0)}% [${ev.distress?.level || '-'}]`;
    case 'restatement':
      return `💬 "${ev.restatement}"`;
    case 'VERIFIED':
      return `✅ VERIFIED — Confidence ${(ev.confidence * 100).toFixed(0)}%`;
    case 'SAFE_HUMAN_TAKEOVER':
      return `⚠ HUMAN TAKEOVER — ${ev.reason}`;
    case 'error':
      return `❌ ${ev.message}`;
    default:
      return JSON.stringify(ev);
  }
}
