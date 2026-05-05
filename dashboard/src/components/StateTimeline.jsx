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
  LISTEN: '#818cf8',      // Indigo
  SCRUB: '#f59e0b',       // Amber
  ANALYZE: '#c084fc',     // Purple
  RESTATE: '#38bdf8',     // Light Blue
  WAIT_FOR_CONFIRM: '#f59e0b', // Amber
  VERIFIED: '#2dd4a0',    // Teal
  HUMAN_TAKEOVER: '#ef4444', // Red
};

export default function StateTimeline({ currentState }) {
  const currentIdx = STATES.findIndex((s) => s.key === currentState);

  if (currentState === 'HUMAN_TAKEOVER') {
    return (
      <div className="glass-card flex items-center justify-center py-4 bg-red-500/10 border-red-500/20 shadow-[0_0_15px_rgba(239,68,68,0.1)]">
        <div className="flex items-center gap-3 animate-fade-in">
          <div className="relative">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <div className="absolute inset-0 rounded-full animate-ping bg-red-500 opacity-50" />
          </div>
          <span className="text-sm font-bold uppercase tracking-widest text-red-400">
            ⚠ Human Takeover Activated
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-card overflow-hidden bg-black/20 border-white/5 shadow-2xl px-6 py-4">
      <div className="flex items-center justify-between min-w-max w-full">
        {STATES.map((s, i) => {
          const isPast = i < currentIdx;
          const isActive = s.key === currentState;
          const isFuture = i > currentIdx;
          const color = isActive
            ? STATE_COLORS[s.key]
            : isPast
              ? '#2dd4a0'
              : 'rgba(255, 255, 255, 0.2)';

          return (
            <div key={s.key} className="flex items-center flex-1 last:flex-none">
              {/* Node */}
              <div className="flex flex-col items-center gap-2 relative z-10 w-16">
                <div
                  className={`relative flex items-center justify-center w-10 h-10 rounded-full border-2 transition-all duration-500 ${isActive ? 'scale-110' : ''}`}
                  style={{
                    borderColor: color,
                    background: isActive ? `${color}20` : 'rgba(0,0,0,0.4)',
                    boxShadow: isActive ? `0 0 20px ${color}40` : 'none',
                  }}
                >
                  <span className="text-sm drop-shadow-md z-10" style={{ filter: !isActive && !isPast ? 'grayscale(100%) opacity(50%)' : 'none' }}>
                    {s.icon}
                  </span>
                  {isActive && (
                    <div
                      className="absolute inset-0 rounded-full animate-ping opacity-30"
                      style={{ background: color, animationDuration: '2s' }}
                    />
                  )}
                </div>
                <span
                  className={`text-[9px] font-bold uppercase tracking-widest transition-colors duration-300 text-center w-max ${isActive ? 'drop-shadow-md' : ''}`}
                  style={{ color: isActive ? color : isPast ? '#2dd4a0' : 'rgba(255, 255, 255, 0.4)' }}
                >
                  {s.label}
                </span>
              </div>
              
              {/* Connector */}
              {i < STATES.length - 1 && (
                <div className="flex-1 px-2 -ml-2 -mr-2 relative z-0 mt-[-20px]">
                  <div
                    className="h-[2px] rounded-full transition-colors duration-500 w-full"
                    style={{
                      background: isPast ? '#2dd4a0' : 'rgba(255, 255, 255, 0.1)',
                      boxShadow: isPast ? '0 0 10px rgba(45,212,160,0.5)' : 'none',
                    }}
                  >
                    {isActive && (
                      <div className="h-full w-1/2 bg-gradient-to-r from-transparent to-white/50 animate-[shimmer_2s_infinite]" />
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
