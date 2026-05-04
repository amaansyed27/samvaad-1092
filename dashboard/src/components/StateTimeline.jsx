/**
 * StateTimeline — Visual representation of the Verification State Machine.
 *
 * Shows each phase as a node in a horizontal pipeline, highlighting the
 * current active state with a pulsing indicator.
 */

const STATES = [
  { key: 'LISTEN', label: 'Listen', icon: '🎙' },
  { key: 'SCRUB', label: 'Scrub PII', icon: '🛡' },
  { key: 'ANALYZE', label: 'Analyse', icon: '🧠' },
  { key: 'RESTATE', label: 'Restate', icon: '💬' },
  { key: 'WAIT_FOR_CONFIRM', label: 'Confirm', icon: '✓' },
  { key: 'VERIFIED', label: 'Verified', icon: '✅' },
];

const STATE_COLORS = {
  LISTEN: 'var(--color-listening)',
  SCRUB: 'var(--color-warning)',
  ANALYZE: 'var(--color-analyzing)',
  RESTATE: 'var(--color-analyzing)',
  WAIT_FOR_CONFIRM: 'var(--color-warning)',
  VERIFIED: 'var(--color-verified)',
  HUMAN_TAKEOVER: 'var(--color-critical)',
};

export default function StateTimeline({ currentState }) {
  const currentIdx = STATES.findIndex((s) => s.key === currentState);

  if (currentState === 'HUMAN_TAKEOVER') {
    return (
      <div className="glass-card p-4 flex items-center justify-center gap-3 animate-fade-in">
        <div
          className="state-dot"
          style={{ background: 'var(--color-critical)', width: 12, height: 12 }}
        />
        <span className="text-sm font-semibold uppercase tracking-wider" style={{ color: 'var(--color-critical)' }}>
          ⚠ Human Takeover Activated
        </span>
      </div>
    );
  }

  return (
    <div className="glass-card p-4 overflow-x-auto">
      <div className="flex items-center gap-1 min-w-max">
        {STATES.map((s, i) => {
          const isPast = i < currentIdx;
          const isActive = s.key === currentState;
          const isFuture = i > currentIdx;
          const color = isActive
            ? STATE_COLORS[s.key]
            : isPast
              ? 'var(--color-verified)'
              : 'var(--color-text-muted)';

          return (
            <div key={s.key} className="flex items-center">
              {/* Node */}
              <div className="flex flex-col items-center gap-1.5 px-3">
                <div
                  className="relative flex items-center justify-center w-9 h-9 rounded-full border-2 transition-all duration-500"
                  style={{
                    borderColor: color,
                    background: isActive ? `${color}15` : 'transparent',
                  }}
                >
                  <span className="text-sm">{s.icon}</span>
                  {isActive && (
                    <div
                      className="absolute inset-0 rounded-full animate-ping opacity-20"
                      style={{ background: color }}
                    />
                  )}
                </div>
                <span
                  className="text-[10px] font-medium uppercase tracking-wider transition-colors duration-300"
                  style={{ color }}
                >
                  {s.label}
                </span>
              </div>
              {/* Connector */}
              {i < STATES.length - 1 && (
                <div
                  className="w-8 h-[2px] rounded-full transition-colors duration-500"
                  style={{
                    background: isPast ? 'var(--color-verified)' : 'var(--color-glass-border)',
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
