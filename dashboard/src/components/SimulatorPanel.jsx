import { useState } from 'react';

/**
 * SimulatorPanel — Development tool for testing the verification pipeline.
 *
 * Allows operators to manually send transcript text and confirmation
 * signals to the backend, simulating a real call flow.
 */
export default function SimulatorPanel({ onSendTranscript, onSendConfirm, state, restatement, connected }) {
  const [text, setText] = useState('');

  const handleSend = () => {
    if (text.trim()) {
      onSendTranscript(text.trim());
      setText('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isWaiting = state === 'WAIT_FOR_CONFIRM';
  const isTerminal = state === 'VERIFIED' || state === 'HUMAN_TAKEOVER';

  return (
    <div className="glass-card p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
          Call Simulator
        </h3>
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{ background: connected ? 'var(--color-verified)' : 'var(--color-critical)' }}
          />
          <span className="text-[10px] text-[var(--color-text-muted)]">
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>

      {/* Restatement display */}
      {restatement && isWaiting && (
        <div className="p-4 rounded-lg bg-[rgba(99,102,241,0.06)] border border-[rgba(99,102,241,0.15)] animate-slide-up">
          <span className="text-[10px] uppercase tracking-wider text-[var(--color-listening)]">
            AI Restatement — Awaiting Confirmation
          </span>
          <p className="mt-2 text-sm text-[var(--color-text-primary)] leading-relaxed italic">
            "{restatement}"
          </p>
          <div className="mt-3 flex gap-2">
            <button
              onClick={() => onSendConfirm(true)}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold uppercase tracking-wider transition-all duration-200
                hover:scale-[1.02] active:scale-[0.98]"
              style={{
                background: 'rgba(45, 212, 160, 0.12)',
                color: 'var(--color-verified)',
                border: '1px solid rgba(45, 212, 160, 0.2)',
              }}
            >
              ✓ Confirmed
            </button>
            <button
              onClick={() => onSendConfirm(false)}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold uppercase tracking-wider transition-all duration-200
                hover:scale-[1.02] active:scale-[0.98]"
              style={{
                background: 'rgba(239, 68, 68, 0.12)',
                color: 'var(--color-critical)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
              }}
            >
              ✗ Incorrect
            </button>
          </div>
        </div>
      )}

      {/* Transcript input */}
      {!isTerminal && (
        <div className="space-y-2">
          <label className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
            Simulate Caller Speech
          </label>
          <div className="flex gap-2">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type caller transcript here… (Kannada, Hindi, or English)"
              rows={2}
              className="flex-1 px-3 py-2 rounded-lg text-sm bg-[var(--color-elevated)] border border-[var(--color-glass-border)]
                text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:border-[var(--color-listening)] transition-colors resize-none"
            />
            <button
              onClick={handleSend}
              disabled={!text.trim() || !connected}
              className="px-4 rounded-lg text-xs font-semibold uppercase tracking-wider transition-all duration-200
                hover:scale-[1.02] active:scale-[0.98] disabled:opacity-30 disabled:pointer-events-none"
              style={{
                background: 'rgba(99, 102, 241, 0.12)',
                color: 'var(--color-listening)',
                border: '1px solid rgba(99, 102, 241, 0.2)',
              }}
            >
              Send
            </button>
          </div>
        </div>
      )}

      {/* Terminal states */}
      {state === 'VERIFIED' && (
        <div className="p-4 rounded-lg bg-[rgba(45,212,160,0.08)] border border-[rgba(45,212,160,0.15)] text-center animate-slide-up">
          <span className="text-lg">✅</span>
          <p className="mt-1 text-sm font-semibold" style={{ color: 'var(--color-verified)' }}>
            Call Verified Successfully
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            Understanding confirmed. Call can proceed to dispatch.
          </p>
        </div>
      )}

      {state === 'HUMAN_TAKEOVER' && (
        <div className="p-4 rounded-lg bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.15)] text-center animate-slide-up">
          <span className="text-lg">⚠</span>
          <p className="mt-1 text-sm font-semibold" style={{ color: 'var(--color-critical)' }}>
            Human Agent Takeover
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            Call has been escalated to a human operator.
          </p>
        </div>
      )}
    </div>
  );
}
