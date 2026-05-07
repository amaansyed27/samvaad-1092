
import RadialGauge from './RadialGauge';
import StateTimeline from './StateTimeline';
import TranscriptPanel from './TranscriptPanel';
import AnalysisCard from './AnalysisCard';
import SimulatorPanel from './SimulatorPanel';

export default function LiveTerminal({
  connected, callId, state, events, distress, analysis, restatement, ttsAudio,
  assistantText, confidence, piiCount, liveTranscript, partialTranscript, languageCode, selectedLanguage,
  location, mlRouting, slots, latencyMetrics, isAssistantSpeaking,
  sendTranscript, sendConfirm, sendAudio, sendAudioFrame, sendAudioEnd,
  sendLanguageSelect, sendTakeover, sendAgentEdit, sendLocationPin, debugMode
}) {
  return (
    <div className="flex-1 flex gap-px bg-white/5 overflow-hidden">
      {/* Left: Intelligence & Control */}
      <aside className="w-80 flex flex-col bg-[#030304] overflow-y-auto custom-scrollbar">
        {/* Telemetry Section */}
        <div className="p-6 border-b border-white/5 bg-white/[0.01]">
          <h2 className="text-[10px] font-black text-white/20 uppercase tracking-[0.2em] mb-6">Biometric Telemetry</h2>
          <div className="flex flex-col gap-8">
            <div className="flex justify-around items-center">
              <RadialGauge
                value={distress.score} size={110} label="Distress" sublabel={distress.level}
                color="var(--color-critical)" thresholds={[ { at: 0, color: 'var(--color-verified)' }, { at: 0.4, color: 'var(--color-warning)' }, { at: 0.7, color: 'var(--color-critical)' } ]}
              />
              <RadialGauge
                value={confidence} size={110} label="Confidence" sublabel={confidence > 0.8 ? 'TRUSTED' : 'EVALUATING'}
                color="var(--color-verified)"
              />
            </div>
            {/* Spectral Features */}
            <div className="space-y-3">
              {Object.entries(distress.features || {}).slice(0, 4).map(([key, val]) => (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-[8px] font-mono text-white/30 uppercase w-12 text-right">{key}</span>
                  <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
                    <div className="h-full bg-indigo-500/50 shadow-[0_0_10px_rgba(99,102,241,0.3)] transition-all duration-500" style={{ width: `${val * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Call Control Simulator */}
        {debugMode && (
          <div className="flex-1 flex flex-col min-h-0 bg-white/[0.01]">
            <SimulatorPanel
              onSendTranscript={sendTranscript}
              onSendConfirm={sendConfirm}
              onSendAudio={sendAudio}
              onSendAudioFrame={sendAudioFrame}
              onSendAudioEnd={sendAudioEnd}
              onSetLanguage={sendLanguageSelect}
              onSendTakeover={sendTakeover}
              onSendLocationPin={sendLocationPin}
              state={state}
              restatement={restatement || assistantText}
              ttsAudio={ttsAudio}
              connected={connected}
              languageCode={languageCode}
              selectedLanguage={selectedLanguage}
              partialTranscript={partialTranscript}
              slots={slots}
              latencyMetrics={latencyMetrics}
              isAssistantSpeaking={isAssistantSpeaking}
            />
          </div>
        )}
        {!debugMode && (
           <div className="p-6 flex flex-col items-center justify-center text-center flex-1">
             <div className="w-12 h-12 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center mb-4 animate-pulse">
               <span className="text-xl">📞</span>
             </div>
             <p className="text-[10px] font-bold text-white/40 uppercase tracking-widest">Listening on Twilio Gateway...</p>
             <p className="text-xs text-white/20 mt-2">Dial your 1092 number to begin.</p>
           </div>
        )}
      </aside>

      {/* Center: Live Monitoring */}
      <section className="flex-1 flex flex-col bg-[#030304] min-w-0">
        <div className="h-20 flex items-center px-8 border-b border-white/5 bg-white/[0.01]">
          <StateTimeline currentState={state} />
        </div>
        <div className="flex-1 min-h-0">
          <TranscriptPanel events={events} piiCount={piiCount} partialTranscript={partialTranscript} />
        </div>
      </section>

      {/* Right: Automated Analysis */}
      <aside className="w-96 flex flex-col bg-[#030304] border-l border-white/5">
        <AnalysisCard analysis={analysis} mlRouting={mlRouting} sentiment={events.find(e => e.sentiment)?.sentiment} language={languageCode} slots={slots} latencyMetrics={latencyMetrics} onAgentEdit={sendAgentEdit} />
      </aside>
    </div>
  );
}
