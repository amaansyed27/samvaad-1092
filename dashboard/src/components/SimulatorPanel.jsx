import { useState } from 'react';
import { useMicrophone } from '../hooks/useMicrophone';

export default function SimulatorPanel({
  onSendTranscript,
  onSendConfirm,
  onSendAudio,
  onSendAudioFrame,
  onSendAudioEnd,
  onSetLanguage,
  onSendTakeover,
  state,
  restatement,
  ttsAudio,
  connected,
  languageCode,
  selectedLanguage,
  partialTranscript,
  slots = {},
  latencyMetrics = {},
  isAssistantSpeaking,
}) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState('mic'); // 'text' | 'mic'

  const { isRecording, audioLevel, error: micError, startRecording, stopRecording } = useMicrophone({
    onAudioFrame: (base64Data, sampleRate) => {
      if (onSendAudioFrame) onSendAudioFrame(base64Data, sampleRate);
    },
    onAudioEnd: (sampleRate) => {
      if (onSendAudioEnd) onSendAudioEnd(sampleRate);
    },
    onAudioChunk: (base64Data) => {
      if (!onSendAudioFrame && onSendAudio) onSendAudio(base64Data);
    },
    inputBlocked: isAssistantSpeaking,
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
  const isClarifying = Boolean(restatement) && state === 'LISTEN';
  const isTerminal = state === 'VERIFIED' || state === 'HUMAN_TAKEOVER';
  const isActive = !isTerminal && state !== 'INIT';
  const languages = [
    { digit: '1', code: 'en-IN', label: 'English' },
    { digit: '2', code: 'kn-IN', label: 'Kannada' },
    { digit: '3', code: 'hi-IN', label: 'Hindi' },
  ];

  return (
    <div className="glass-card flex flex-col h-full bg-black/20 border-white/5 shadow-2xl relative overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center justify-between px-6 py-5 border-b border-white/5 bg-white/[0.01]">
        <div className="flex flex-col">
          <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-white/40">
            Emergency Diagnostics
          </h3>
          <span className="text-[8px] text-white/10 uppercase tracking-widest font-bold mt-0.5">Real-time LLM Inference</span>
        </div>
        
        {/* Mode toggle */}
        {!isTerminal && (
          <div className="flex rounded bg-black/60 border border-white/10 p-0.5">
            <button
              onClick={() => setMode('mic')}
              className={`px-3 py-1 text-[9px] font-black uppercase tracking-widest transition-all duration-300 rounded ${mode === 'mic' ? 'bg-red-500/20 text-red-400' : 'text-white/20 hover:text-white/40'}`}
            >
              Hardware
            </button>
            <button
              onClick={() => setMode('text')}
              className={`px-3 py-1 text-[9px] font-black uppercase tracking-widest transition-all duration-300 rounded ${mode === 'text' ? 'bg-indigo-500/20 text-indigo-400' : 'text-white/20 hover:text-white/40'}`}
            >
              Simulator
            </button>
          </div>
        )}
      </div>


      <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar flex flex-col">
        {!isTerminal && (
          <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10 flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] font-bold uppercase tracking-widest text-white/40">
                Caller Language
              </span>
              <span className="text-[9px] font-mono text-white/30 uppercase">
                Press 1 / 2 / 3
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {languages.map((lang) => (
                <button
                  key={lang.code}
                  onClick={() => onSetLanguage?.(lang.code)}
                  disabled={!connected}
                  className={`h-10 rounded-lg border text-[10px] font-black uppercase tracking-widest transition-all ${
                    selectedLanguage === lang.code
                      ? 'bg-indigo-500/20 border-indigo-400/50 text-indigo-200'
                      : 'bg-black/30 border-white/10 text-white/40 hover:text-white/70'
                  } disabled:opacity-30 disabled:pointer-events-none`}
                >
                  {lang.digit} {lang.label}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10 flex-shrink-0 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/40">
              Required Slots
            </span>
            <span className="text-[9px] font-mono text-indigo-300 uppercase">
              {slots.required_slot || 'issue'}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <SlotPill label="Issue" value={slots.issue || 'Pending'} />
            <SlotPill label="Dept" value={slots.department || 'UNASSIGNED'} />
            <SlotPill label="Location" value={slots.location || 'Pending'} />
            <SlotPill label="Specific" value={slots.location_specific ? 'Yes' : 'No'} tone={slots.location_specific ? 'good' : 'warn'} />
          </div>
          {partialTranscript && (
            <p className="text-xs text-white/70 leading-relaxed border-l border-indigo-400/40 pl-3">
              {partialTranscript}
            </p>
          )}
        </div>

        <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10 flex-shrink-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-white/40 mb-3">
            Latency
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Metric label="Partial" value={latencyMetrics.stt_first_partial_ms} />
            <Metric label="Final" value={latencyMetrics.stt_final_ms} />
            <Metric label="Analysis" value={latencyMetrics.analysis_ms} />
            <Metric label="TTS" value={latencyMetrics.tts_first_audio_ms} />
          </div>
          {isAssistantSpeaking && (
            <div className="mt-3 text-[10px] uppercase tracking-widest text-emerald-300">
              Assistant speaking
            </div>
          )}
        </div>

        <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10 flex-shrink-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-white/40 mb-3">
            Judge Demo Script
          </div>
          <div className="space-y-2 text-[11px] text-white/55 leading-relaxed">
            <p><span className="text-white/80 font-bold">English:</span> Power cuts at my house in Whitefield, near Vydehi hospital.</p>
            <p><span className="text-white/80 font-bold">Hindi:</span> Mere area mein baar baar bijli ja rahi hai, Whitefield main road ke paas.</p>
            <p><span className="text-white/80 font-bold">Kannada:</span> Whitefield Vydehi hospital hattira current hogide.</p>
          </div>
        </div>
        
        {/* Restatement display */}
        {restatement && (isWaiting || isClarifying) && (
          <div className="p-5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 shadow-inner animate-slide-up flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-400">
                AI Restatement
              </span>
              {ttsAudio && (
                <button
                  onClick={handleReplayTTS}
                  className="px-3 py-1 rounded bg-indigo-500/20 text-[10px] font-bold tracking-wider text-indigo-300 hover:bg-indigo-500/30 transition-colors uppercase"
                >
                  🔊 Replay TTS
                </button>
              )}
            </div>
            <p className="text-sm text-indigo-100 font-medium leading-relaxed italic border-l-2 border-indigo-500/50 pl-3">
              "{restatement}"
            </p>
            {isWaiting && (
            <div className="mt-4 flex gap-3">
              <button
                onClick={() => onSendConfirm(true)}
                className="flex-1 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all duration-200 shadow-lg hover:scale-[1.02] active:scale-[0.98]"
                style={{
                  background: 'rgba(45, 212, 160, 0.15)',
                  color: '#2dd4a0',
                  border: '1px solid rgba(45, 212, 160, 0.3)',
                  boxShadow: '0 0 15px rgba(45,212,160,0.1)'
                }}
              >
                ✓ Confirmed
              </button>
              <button
                onClick={() => onSendConfirm(false)}
                className="flex-1 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all duration-200 shadow-lg hover:scale-[1.02] active:scale-[0.98]"
                style={{
                  background: 'rgba(239, 68, 68, 0.15)',
                  color: '#ef4444',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  boxShadow: '0 0 15px rgba(239,68,68,0.1)'
                }}
              >
                ✗ Incorrect
              </button>
            </div>
            )}
            {isClarifying && (
              <p className="mt-3 text-[10px] uppercase tracking-widest text-indigo-300/70">
                Awaiting caller detail
              </p>
            )}
          </div>
        )}

        {/* ── Input Area ─────────────────────────────────────────────────── */}
        {!isTerminal && mode === 'text' && (
          <div className="flex-1 flex flex-col justify-center">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/40 mb-2">
              Text Input Simulator
            </span>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type caller transcript here… (Kannada, Hindi, or English)"
              className="w-full h-32 px-4 py-3 rounded-xl text-sm font-medium bg-black/40 border border-white/10
                text-white/90 placeholder:text-white/20 focus:outline-none focus:border-indigo-500/50 shadow-inner resize-none transition-colors"
            />
            <button
              onClick={handleSend}
              disabled={!text.trim() || !connected}
              className="mt-3 w-full py-3 rounded-xl text-[10px] font-bold uppercase tracking-widest transition-all duration-200
                hover:bg-indigo-500/20 active:scale-[0.98] disabled:opacity-30 disabled:pointer-events-none"
              style={{
                background: 'rgba(99, 102, 241, 0.15)',
                color: '#818cf8',
                border: '1px solid rgba(99, 102, 241, 0.3)',
              }}
            >
              Send Transcript
            </button>
          </div>
        )}

        {/* ── Microphone Mode ───────────────────────────────────────────── */}
        {!isTerminal && mode === 'mic' && (
          <div className="flex-1 flex flex-col items-center justify-center">
            <div className="relative w-32 h-32 flex items-center justify-center mb-6">
              {/* Pulsing rings */}
              {isRecording && (
                <>
                  <div
                    className="absolute inset-0 rounded-full animate-ping opacity-20"
                    style={{ background: '#ef4444', animationDuration: '1.5s' }}
                  />
                  <div
                    className="absolute rounded-full transition-all duration-150"
                    style={{
                      inset: `${(1 - audioLevel) * 20}px`,
                      background: `rgba(239, 68, 68, ${0.1 + audioLevel * 0.4})`,
                      borderRadius: '50%',
                      boxShadow: `0 0 ${20 + audioLevel * 40}px rgba(239,68,68,0.4)`
                    }}
                  />
                </>
              )}
              {/* Mic button */}
              <button
                onClick={isRecording ? stopRecording : startRecording}
                disabled={!connected}
                className="relative z-10 w-20 h-20 rounded-full flex items-center justify-center transition-all duration-300
                  hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100"
                style={{
                  background: isRecording ? 'rgba(239, 68, 68, 0.2)' : 'rgba(255,255,255,0.05)',
                  border: `2px solid ${isRecording ? '#ef4444' : 'rgba(255,255,255,0.1)'}`,
                  boxShadow: isRecording ? '0 0 30px rgba(239,68,68,0.3)' : '0 10px 25px rgba(0,0,0,0.5)',
                }}
              >
                <span className="text-3xl drop-shadow-lg">{isRecording ? '⏹' : '🎙'}</span>
              </button>
            </div>
            
            <div className="flex flex-col items-center gap-2">
              <span className={`text-xs font-bold uppercase tracking-widest ${isRecording ? 'text-red-400 animate-pulse' : 'text-white/40'}`}>
                {isRecording ? 'Recording Live Audio' : 'Tap to Start Recording'}
              </span>
              {isRecording && (
                <span className="text-[10px] text-red-400/60 uppercase tracking-widest">
                  {isAssistantSpeaking ? 'Waiting for assistant audio to finish...' : 'Streaming 16 kHz PCM frames...'}
                </span>
              )}
              {micError && (
                <span className="text-[10px] text-red-400 bg-red-500/10 px-3 py-1 rounded-full border border-red-500/20 mt-2">
                  ⚠ {micError}
                </span>
              )}
            </div>
          </div>
        )}

        {/* ── Manual Takeover Button ──────────────────────────────────── */}
        <div className="mt-auto pt-4 border-t border-white/5">
          {isActive && !isTerminal && (
            <button
              onClick={() => onSendTakeover?.('Agent initiated manual takeover')}
              className="w-full py-3 rounded-xl text-[10px] font-bold uppercase tracking-widest transition-all duration-200
                hover:scale-[1.01] active:scale-[0.99] shadow-lg"
              style={{
                background: 'rgba(239, 68, 68, 0.1)',
                color: '#ef4444',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                boxShadow: '0 0 15px rgba(239,68,68,0.1)'
              }}
            >
              ⚠ Initiate Manual Takeover
            </button>
          )}

          {/* Terminal states */}
          {state === 'VERIFIED' && (
            <div className="p-5 rounded-xl bg-[#2dd4a0]/10 border border-[#2dd4a0]/20 text-center animate-slide-up shadow-[0_0_20px_rgba(45,212,160,0.1)]">
              <span className="text-3xl drop-shadow-lg mb-2 block">✅</span>
              <p className="text-sm font-bold uppercase tracking-widest text-[#2dd4a0]">
                Verified Successfully
              </p>
              <p className="mt-2 text-xs text-[#2dd4a0]/60 font-medium">
                Intent confirmed. Escalating to dispatch.
              </p>
            </div>
          )}

          {state === 'HUMAN_TAKEOVER' && (
            <div className="p-5 rounded-xl bg-red-500/10 border border-red-500/20 text-center animate-slide-up shadow-[0_0_20px_rgba(239,68,68,0.1)]">
              <span className="text-3xl drop-shadow-lg mb-2 block">⚠</span>
              <p className="text-sm font-bold uppercase tracking-widest text-red-400">
                Agent Takeover
              </p>
              <p className="mt-2 text-xs text-red-400/60 font-medium">
                AI bypassed. Human operator in control.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SlotPill({ label, value, tone }) {
  const color = tone === 'good' ? '#2dd4a0' : tone === 'warn' ? '#f5a524' : '#8b5cf6';
  return (
    <div className="rounded bg-black/30 border border-white/10 px-2 py-2 min-w-0">
      <div className="text-[8px] font-black uppercase tracking-widest text-white/25">{label}</div>
      <div className="text-[10px] font-bold uppercase truncate" style={{ color }}>{value}</div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded bg-black/30 border border-white/10 px-2 py-2">
      <div className="text-[8px] font-black uppercase tracking-widest text-white/25">{label}</div>
      <div className="text-[10px] font-mono font-bold text-white/70">
        {Number.isFinite(value) ? `${Math.round(value)} ms` : '--'}
      </div>
    </div>
  );
}
