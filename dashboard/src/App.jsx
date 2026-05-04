import './index.css';
import { useCallSocket } from './hooks/useCallSocket';
import RadialGauge from './components/RadialGauge';
import StateTimeline from './components/StateTimeline';
import TranscriptPanel from './components/TranscriptPanel';
import AnalysisCard from './components/AnalysisCard';
import SimulatorPanel from './components/SimulatorPanel';

/**
 * App — Samvaad 1092 Operator Dashboard
 *
 * Minimalist monochrome glassmorphism interface designed for
 * low cognitive load during emergency call handling.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────┐
 *   │                  Header Bar                      │
 *   ├────────────┬────────────────────┬────────────────┤
 *   │  Distress  │                    │  Confidence    │
 *   │   Gauge    │  State Timeline    │    Gauge       │
 *   ├────────────┼────────────────────┼────────────────┤
 *   │            │                    │                │
 *   │ Transcript │   Analysis Card    │  Simulator     │
 *   │   Panel    │                    │   Panel        │
 *   │            │                    │                │
 *   └────────────┴────────────────────┴────────────────┘
 */
export default function App() {
  const {
    connected,
    callId,
    state,
    events,
    distress,
    analysis,
    restatement,
    confidence,
    piiCount,
    sendTranscript,
    sendConfirm,
  } = useCallSocket();

  return (
    <div className="h-screen flex flex-col bg-[var(--color-void)] overflow-hidden">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-glass-border)]">
        <div className="flex items-center gap-4">
          {/* Logo / Title */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[rgba(99,102,241,0.15)] flex items-center justify-center">
              <span className="text-base">📞</span>
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-wide text-[var(--color-text-primary)]">
                SAMVAAD 1092
              </h1>
              <p className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-widest">
                Karnataka Emergency Helpline
              </p>
            </div>
          </div>

          {/* Call ID badge */}
          {callId && (
            <div className="status-badge ml-4" style={{ background: 'var(--color-glass)', border: '1px solid var(--color-glass-border)' }}>
              <span className="text-[var(--color-text-muted)]">Call</span>
              <span className="font-mono text-[var(--color-text-secondary)]">{callId}</span>
            </div>
          )}
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider">
            {state}
          </span>
          <div className="flex items-center gap-1.5">
            <div
              className="w-2 h-2 rounded-full transition-colors duration-300"
              style={{ background: connected ? 'var(--color-verified)' : 'var(--color-critical)' }}
            />
            <span className="text-[10px] text-[var(--color-text-muted)]">
              {connected ? 'Live' : 'Offline'}
            </span>
          </div>
        </div>
      </header>

      {/* ── Main Content ───────────────────────────────────────────────── */}
      <main className="flex-1 p-4 overflow-hidden flex flex-col gap-4">
        {/* Row 1: Gauges + State Timeline */}
        <div className="flex gap-4 items-stretch">
          {/* Distress Gauge */}
          <div className="glass-card p-5 flex flex-col items-center justify-center" style={{ minWidth: 200 }}>
            <RadialGauge
              value={distress.score}
              label="Distress"
              sublabel={distress.level}
              color="var(--color-verified)"
              thresholds={[
                { at: 0.35, color: 'var(--color-warning)' },
                { at: 0.60, color: '#f97316' },
                { at: 0.85, color: 'var(--color-critical)' },
              ]}
            />
            {/* Feature breakdown */}
            <div className="mt-3 w-full space-y-1.5">
              {Object.entries(distress.features || {}).map(([key, val]) => (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-[9px] text-[var(--color-text-muted)] uppercase w-14 text-right">{key}</span>
                  <div className="flex-1 h-1 rounded-full bg-[var(--color-glass-border)] overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${val * 100}%`,
                        background: val > 0.7 ? 'var(--color-critical)' : val > 0.4 ? 'var(--color-warning)' : 'var(--color-text-muted)',
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* State Timeline — expands to fill */}
          <div className="flex-1 flex items-center">
            <div className="w-full">
              <StateTimeline currentState={state} />
            </div>
          </div>

          {/* Confidence Gauge */}
          <div className="glass-card p-5 flex flex-col items-center justify-center" style={{ minWidth: 200 }}>
            <RadialGauge
              value={confidence}
              label="Confidence"
              sublabel={confidence > 0.8 ? 'HIGH' : confidence > 0.5 ? 'MODERATE' : 'LOW'}
              color="var(--color-verified)"
              thresholds={[
                { at: 0, color: 'var(--color-critical)' },
                { at: 0.5, color: 'var(--color-warning)' },
                { at: 0.8, color: 'var(--color-verified)' },
              ]}
            />
          </div>
        </div>

        {/* Row 2: Transcript + Analysis + Simulator */}
        <div className="flex-1 grid grid-cols-3 gap-4 overflow-hidden">
          {/* Transcript */}
          <TranscriptPanel events={events} piiCount={piiCount} />

          {/* Analysis */}
          <AnalysisCard
            analysis={analysis}
            sentiment={events.find(e => e.sentiment)?.sentiment}
            language={events.find(e => e.state === 'ANALYZE')?.language}
          />

          {/* Simulator */}
          <SimulatorPanel
            onSendTranscript={sendTranscript}
            onSendConfirm={sendConfirm}
            state={state}
            restatement={restatement}
            connected={connected}
          />
        </div>
      </main>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer className="px-6 py-2 border-t border-[var(--color-glass-border)] flex items-center justify-between">
        <span className="text-[10px] text-[var(--color-text-muted)]">
          Samvaad 1092 • AI for Bharat 2 • v0.1.0
        </span>
        <span className="text-[10px] text-[var(--color-text-muted)]">
          🛡 PII scrubbed locally — no raw data leaves this device
        </span>
      </footer>
    </div>
  );
}
