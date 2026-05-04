import { useState } from 'react';
import { useMicrophone } from '../hooks/useMicrophone';

/**
 * SimulatorPanel — Combined Microphone + Text simulator and control panel.
 *
 * Features:
 *   - Live microphone recording with audio level visualiser
 *   - Text-based transcript input (simulator mode)
 *   - Restatement display with TTS playback controls
 *   - Manual takeover button (emergency escalation)
 *   - Confirmation buttons (verified / incorrect)
 */
export default function SimulatorPanel({
  onSendTranscript,
  onSendConfirm,
  onSendAudio,
  onSendTakeover,
  state,
  restatement,
  ttsAudio,
  connected,
  languageCode,
}) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState('text'); // 'text' | 'mic'

  const { isRecording, audioLevel, error: micError, startRecording, stopRecording } = useMicrophone({
    onAudioChunk: (base64Data) => {
      if (onSendAudio) onSendAudio(base64Data);
    },
    chunkIntervalMs: 3000,
  });

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

  const handleReplayTTS = () => {
    if (ttsAudio) {
      try {
        const byteChars = atob(ttsAudio);
        const byteArray = new Uint8Array(byteChars.length);
        for (let i = 0; i < byteChars.length; i++) {
          byteArray[i] = byteChars.charCodeAt(i);
        }
        const blob = new Blob([byteArray], { type: 'audio/wav' });
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        audio.play();
        audio.addEventListener('ended', () => URL.revokeObjectURL(audioUrl));
      } catch (err) {
        console.error('[TTS Replay] Error:', err);
      }
    }
  };

  const isWaiting = state === 'WAIT_FOR_CONFIRM';
  const isTerminal = state === 'VERIFIED' || state === 'HUMAN_TAKEOVER';
  const isActive = !isTerminal && state !== 'INIT';

  // Map language codes to display names
  const langName = {
    'kn-IN': 'Kannada', 'hi-IN': 'Hindi', 'en-IN': 'English',
    'unknown': 'Detecting…',
  }[languageCode] || languageCode || 'Detecting…';

  return (
    <div className="glass-card p-5 space-y-4 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
          Call Interface
        </h3>
        <div className="flex items-center gap-3">
          {/* Language indicator */}
          {isActive && (
            <span className="status-badge" style={{
              background: 'rgba(139, 92, 246, 0.08)',
              color: 'var(--color-analyzing)',
              border: '1px solid rgba(139, 92, 246, 0.12)',
            }}>
              🌐 {langName}
            </span>
          )}
          <div className="flex items-center gap-1.5">
            <div
              className="w-2 h-2 rounded-full"
              style={{ background: connected ? 'var(--color-verified)' : 'var(--color-critical)' }}
            />
            <span className="text-[10px] text-[var(--color-text-muted)]">
              {connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>
      </div>

      {/* Mode toggle */}
      {!isTerminal && (
        <div className="flex rounded-lg overflow-hidden border border-[var(--color-glass-border)]">
          <button
            onClick={() => setMode('text')}
            className="flex-1 py-1.5 text-[10px] font-semibold uppercase tracking-wider transition-all duration-200"
            style={{
              background: mode === 'text' ? 'rgba(99, 102, 241, 0.1)' : 'transparent',
              color: mode === 'text' ? 'var(--color-listening)' : 'var(--color-text-muted)',
            }}
          >
            📝 Text Simulator
          </button>
          <button
            onClick={() => setMode('mic')}
            className="flex-1 py-1.5 text-[10px] font-semibold uppercase tracking-wider transition-all duration-200"
            style={{
              background: mode === 'mic' ? 'rgba(239, 68, 68, 0.1)' : 'transparent',
              color: mode === 'mic' ? 'var(--color-critical)' : 'var(--color-text-muted)',
            }}
          >
            🎙 Live Mic
          </button>
        </div>
      )}

      {/* Restatement display */}
      {restatement && isWaiting && (
        <div className="p-4 rounded-lg bg-[rgba(99,102,241,0.06)] border border-[rgba(99,102,241,0.15)] animate-slide-up">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] uppercase tracking-wider text-[var(--color-listening)]">
              AI Restatement — Awaiting Confirmation
            </span>
            {ttsAudio && (
              <button
                onClick={handleReplayTTS}
                className="text-[10px] text-[var(--color-listening)] hover:text-[var(--color-text-primary)] transition-colors"
                title="Replay TTS audio"
              >
                🔊 Replay
              </button>
            )}
          </div>
          <p className="text-sm text-[var(--color-text-primary)] leading-relaxed italic">
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

      {/* ── Input Area ─────────────────────────────────────────────────── */}
      {!isTerminal && mode === 'text' && (
        <div className="space-y-2 flex-1">
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

      {/* ── Microphone Mode ───────────────────────────────────────────── */}
      {!isTerminal && mode === 'mic' && (
        <div className="space-y-3 flex-1">
          <div className="flex flex-col items-center gap-3 py-4">
            {/* Audio level visualiser */}
            <div className="relative w-20 h-20 flex items-center justify-center">
              {/* Pulsing rings */}
              {isRecording && (
                <>
                  <div
                    className="absolute inset-0 rounded-full animate-ping opacity-10"
                    style={{ background: 'var(--color-critical)', animationDuration: '1.5s' }}
                  />
                  <div
                    className="absolute rounded-full transition-all duration-200"
                    style={{
                      inset: `${20 - audioLevel * 20}px`,
                      background: `rgba(239, 68, 68, ${0.1 + audioLevel * 0.2})`,
                      borderRadius: '50%',
                    }}
                  />
                </>
              )}
              {/* Mic button */}
              <button
                onClick={isRecording ? stopRecording : startRecording}
                disabled={!connected}
                className="relative z-10 w-14 h-14 rounded-full flex items-center justify-center transition-all duration-300
                  hover:scale-105 active:scale-95 disabled:opacity-30"
                style={{
                  background: isRecording
                    ? 'rgba(239, 68, 68, 0.2)'
                    : 'rgba(99, 102, 241, 0.12)',
                  border: `2px solid ${isRecording ? 'var(--color-critical)' : 'var(--color-listening)'}`,
                }}
              >
                <span className="text-xl">{isRecording ? '⏹' : '🎙'}</span>
              </button>
            </div>
            <span className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider">
              {isRecording ? 'Recording… Tap to stop' : 'Tap to start recording'}
            </span>
            {micError && (
              <span className="text-[10px] text-[var(--color-critical)]">
                ⚠ {micError}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── Manual Takeover Button ──────────────────────────────────── */}
      {isActive && !isTerminal && (
        <button
          onClick={() => onSendTakeover?.('Agent initiated manual takeover')}
          className="w-full py-2 rounded-lg text-xs font-semibold uppercase tracking-wider transition-all duration-200
            hover:scale-[1.01] active:scale-[0.99]"
          style={{
            background: 'rgba(239, 68, 68, 0.06)',
            color: 'var(--color-critical)',
            border: '1px solid rgba(239, 68, 68, 0.15)',
          }}
        >
          ⚠ Manual Takeover
        </button>
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
