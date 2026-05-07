import { useState, useCallback } from 'react';

export default function AnalysisCard({ analysis, mlRouting, sentiment, language, slots = {}, latencyMetrics = {}, onAgentEdit }) {
  const [isEditing, setIsEditing] = useState(false);
  const [edits, setEdits] = useState({});
  const [saved, setSaved] = useState(false);

  const getField = (field, fallback = '—') => {
    if (edits[field] !== undefined) return edits[field];
    if (field === 'sentiment') return sentiment || analysis?.sentiment || fallback;
    if (field === 'language') return language || fallback;
    return analysis?.[field] || fallback;
  };

  const handleEdit = useCallback((field, value) => {
    setEdits(prev => ({ ...prev, [field]: value }));
    setSaved(false);
  }, []);

  const handleSave = useCallback(() => {
    if (Object.keys(edits).length > 0 && onAgentEdit) {
      onAgentEdit(edits);
      setSaved(true);
      setTimeout(() => setIsEditing(false), 1200);
    }
  }, [edits, onAgentEdit]);

  const handleCancel = useCallback(() => {
    setEdits({});
    setIsEditing(false);
  }, []);

  if (!analysis) {
    return (
      <div className="glass-card p-6 flex flex-col items-center justify-center h-full gap-4 bg-black/20 border-white/5">
        <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500/10 to-indigo-500/10 border border-purple-500/20 flex items-center justify-center shadow-lg shadow-purple-500/5">
          <span className="text-2xl drop-shadow-md">🧠</span>
        </div>
        <span className="text-sm font-bold tracking-widest text-white/50 uppercase">
          Awaiting Analysis
        </span>
        <p className="text-xs text-white/30 text-center max-w-[200px] leading-relaxed">
          Send a transcript or start recording to begin verification.
        </p>
      </div>
    );
  }

  const isTerminal = analysis?.state === 'VERIFIED' || analysis?.state === 'HUMAN_TAKEOVER' || analysis?.requires_immediate_takeover;

  const severityColor = {
    critical: '#ef4444',
    high: '#f5a524',
    medium: '#8b5cf6',
    low: '#2dd4a0',
  }[getField('severity')?.toLowerCase()] || '#8a8a96';

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <div className="glass-card flex flex-col h-full bg-black/20 border-white/5 shadow-2xl animate-slide-up">
      {/* Header */}
      <div className="flex-none flex items-center justify-between px-6 py-5 border-b border-white/5 bg-white/[0.01]">
        <div className="flex flex-col">
          <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-white/40">
            Emergency Analytics
          </h3>
          <span className="text-[8px] text-white/10 uppercase tracking-widest font-bold mt-0.5">Semantic Pipeline v2.0</span>
        </div>
        
        <div className="flex items-center gap-3">
          <span
            className="px-3 py-1 rounded-full text-[10px] font-bold tracking-wider uppercase border shadow-sm"
            style={{
              background: `${severityColor}15`,
              color: severityColor,
              borderColor: `${severityColor}30`,
              boxShadow: `0 0 10px ${severityColor}10`
            }}
          >
            {getField('severity')?.toUpperCase() || 'UNKNOWN'}
          </span>
          {!isEditing ? (
            <button
              onClick={() => setIsEditing(true)}
              className="px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all duration-200
                hover:scale-[1.03] active:scale-[0.97] bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 shadow-inner"
            >
              ✏ Edit
            </button>
          ) : (
            <div className="flex items-center gap-2">
              {hasEdits && (
                <button
                  onClick={handleSave}
                  className="px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all duration-200
                    hover:scale-[1.03] active:scale-[0.97] shadow-inner"
                  style={{
                    background: saved ? 'rgba(45, 212, 160, 0.15)' : 'rgba(99, 102, 241, 0.15)',
                    color: saved ? '#2dd4a0' : '#818cf8',
                    border: `1px solid ${saved ? 'rgba(45, 212, 160, 0.3)' : 'rgba(99, 102, 241, 0.3)'}`,
                  }}
                >
                  {saved ? '✓ Saved' : '⬆ Save'}
                </button>
              )}
              <button
                onClick={handleCancel}
                className="px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all duration-200
                  hover:scale-[1.03] active:scale-[0.97] bg-red-500/10 text-red-400 border border-red-500/20 shadow-inner"
              >
                ✗ Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
        {/* Agent edit banner */}
        {isEditing && (
          <div className="p-3 rounded-lg bg-indigo-500/10 border border-indigo-500/20 shadow-inner animate-fade-in flex items-center gap-3">
            <span className="text-indigo-400 text-lg">🎓</span>
            <p className="text-[10px] text-indigo-300 font-bold uppercase tracking-wider">
              Editing Mode — Corrections become learning signals
            </p>
          </div>
        )}

        {/* Grid */}
        <div className="grid grid-cols-2 gap-6">
          <EditableField
            label="Request Type"
            value={getField('request_type', slots?.request_type || 'grievance')}
            isEditing={isEditing}
            isEdited={edits.request_type !== undefined}
            onChange={(v) => handleEdit('request_type', v)}
          />
          <EditableField
            label="Department"
            value={getField('department', mlRouting?.department || 'UNASSIGNED')}
            isEditing={isEditing}
            isEdited={edits.department !== undefined}
            onChange={(v) => handleEdit('department', v)}
          />
          <EditableField
            label="Line Dept"
            value={getField('line_department', slots?.line_department || 'Pending')}
            isEditing={isEditing}
            isEdited={edits.line_department !== undefined}
            onChange={(v) => handleEdit('line_department', v)}
          />
          <EditableField
            label="Type"
            value={getField('emergency_type')}
            isEditing={isEditing}
            isEdited={edits.emergency_type !== undefined}
            onChange={(v) => handleEdit('emergency_type', v)}
          />
          <EditableField
            label="Sentiment"
            value={getField('sentiment')}
            isEditing={isEditing}
            isEdited={edits.sentiment !== undefined}
            onChange={(v) => handleEdit('sentiment', v)}
          />
          <EditableField
            label="Location"
            value={getField('location_hint', 'Not detected')}
            isEditing={isEditing}
            isEdited={edits.location_hint !== undefined}
            onChange={(v) => handleEdit('location_hint', v)}
          />
          <EditableField
            label="Priority"
            value={getField('priority', 'LOW')}
            isEditing={isEditing}
            isEdited={edits.priority !== undefined}
            onChange={(v) => handleEdit('priority', v)}
          />
          <EditableField
            label="Language"
            value={getField('language')}
            isEditing={isEditing}
            isEdited={edits.language !== undefined}
            onChange={(v) => handleEdit('language', v)}
          />
        </div>

        {mlRouting && !isEditing && mlRouting.department !== "UNKNOWN" && (
          <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <div className="flex items-center gap-2">
              <span className="text-emerald-400">⚡</span>
              <span className="text-[10px] text-emerald-300 font-bold uppercase tracking-wider">Fast ML Routed</span>
            </div>
            <span className="text-[10px] text-emerald-400 font-mono">CONF: {(mlRouting.confidence * 100).toFixed(0)}%</span>
          </div>
        )}

        {(analysis.priority_reason || analysis.empathy_note || analysis.abuse_action || analysis.specialized_helpline || analysis.operator_hint || analysis.status_lookup) && (
          <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10 space-y-3">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/40 block">
              Operator Guidance
            </span>
            {analysis.operator_hint && (
              <GuidanceRow label="Routing note" value={analysis.operator_hint} tone="sky" />
            )}
            {analysis.specialized_helpline && (
              <GuidanceRow
                label={analysis.emergency_referral ? 'Emergency referral' : 'Relevant helpline'}
                value={`${analysis.specialized_helpline}${analysis.secondary_department ? ` | also note ${analysis.secondary_department}` : ''}`}
                tone={analysis.emergency_referral ? 'red' : 'amber'}
              />
            )}
            {analysis.status_lookup && (
              <GuidanceRow label="Status lookup" value={analysis.status_lookup} tone="emerald" />
            )}
            {analysis.priority_reason && (
              <GuidanceRow label="Priority basis" value={analysis.priority_reason} tone="amber" />
            )}
            {analysis.empathy_note && (
              <GuidanceRow label="Empathy cue" value={analysis.empathy_note} tone="sky" />
            )}
            {analysis.abuse_action && analysis.abuse_action !== 'ALLOW' && (
              <GuidanceRow
                label={`Spam policy: ${analysis.abuse_action}`}
                value={`${analysis.abuse_risk || 'UNKNOWN'} risk (${Math.round((analysis.abuse_score || 0) * 100)}%). ${analysis.abuse_reason || 'Review before ticketing or blacklist action.'}`}
                tone="red"
              />
            )}
          </div>
        )}

        {Object.keys(slots || {}).length > 0 && (
          <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/40 block mb-3">
              Verification Slots
            </span>
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="Required" value={slots.required_slot || 'issue'} />
              <MiniStat label="Request" value={slots.request_type || 'grievance'} />
              <MiniStat label="Line Dept" value={slots.line_department || 'pending'} />
              <MiniStat label="Service" value={slots.service_or_scheme || 'n/a'} />
              <MiniStat label="Specific" value={slots.location_specific ? 'yes' : 'no'} />
              <MiniStat label="Location" value={slots.location || 'pending'} />
              <MiniStat label="Loc Check" value={slots.location_validation_status || 'missing'} />
              <MiniStat label="Loc Conf" value={Number.isFinite(slots.location_confidence) ? `${Math.round(slots.location_confidence * 100)}%` : '--'} />
              <MiniStat label="Helpline" value={slots.specialized_helpline || 'n/a'} />
              <MiniStat label="Attempts" value={slots.clarification_count ?? 0} />
            </div>
            {slots.location_validation_reason && (
              <div className="mt-3 rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[10px] text-amber-100/80 leading-relaxed">
                {slots.location_validation_reason}
              </div>
            )}
            {(slots.location_source || slots.location_confirmed || slots.geo_pin?.lat) && (
              <div className="mt-3 rounded border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[10px] text-emerald-100/80 leading-relaxed">
                Source: {slots.location_source || 'speech'}
                {slots.location_confirmed ? ' | caller/map confirmed' : ''}
                {slots.geo_pin?.lat ? ` | pin ${Number(slots.geo_pin.lat).toFixed(5)}, ${Number(slots.geo_pin.lng).toFixed(5)}` : ''}
              </div>
            )}
            {Array.isArray(slots.map_candidates) && slots.map_candidates.length > 0 && (
              <div className="mt-3 space-y-2">
                <span className="text-[9px] font-bold uppercase tracking-widest text-white/30">
                  Map Candidates
                </span>
                {slots.map_candidates.slice(0, 3).map((candidate) => (
                  <div key={`${candidate.name}-${candidate.address}`} className="rounded border border-white/10 bg-black/20 px-3 py-2">
                    <div className="text-[10px] font-bold text-white/80">{candidate.name}</div>
                    <div className="text-[9px] text-white/40 leading-relaxed">{candidate.address}</div>
                    <div className="mt-1 text-[9px] text-amber-300/80">
                      {Math.round((candidate.confidence || 0) * 100)}% match
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {Object.keys(latencyMetrics || {}).length > 0 && (
          <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/40 block mb-3">
              Turn Latency
            </span>
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="STT Partial" value={ms(latencyMetrics.stt_first_partial_ms)} />
              <MiniStat label="STT Final" value={ms(latencyMetrics.stt_final_ms)} />
              <MiniStat label="Analysis" value={ms(latencyMetrics.analysis_ms)} />
              <MiniStat label="TTS First" value={ms(latencyMetrics.tts_first_audio_ms)} />
            </div>
          </div>
        )}

        {/* Severity selector when editing */}
        {isEditing && (
          <div className="space-y-2 pt-2 border-t border-white/5">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/40">
              Severity Level
            </span>
            <div className="flex gap-2">
              {['low', 'medium', 'high', 'critical'].map((level) => {
                const colors = {
                  low: '#2dd4a0',
                  medium: '#8b5cf6',
                  high: '#f5a524',
                  critical: '#ef4444',
                };
                const isActive = getField('severity')?.toLowerCase() === level;
                return (
                  <button
                    key={level}
                    onClick={() => handleEdit('severity', level)}
                    className="flex-1 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-widest transition-all duration-200"
                    style={{
                      background: isActive ? `${colors[level]}20` : 'rgba(255,255,255,0.02)',
                      color: isActive ? colors[level] : 'rgba(255,255,255,0.4)',
                      border: `1px solid ${isActive ? `${colors[level]}40` : 'rgba(255,255,255,0.1)'}`,
                    }}
                  >
                    {level}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Key details */}
        {analysis.key_details?.length > 0 && (
          <div className="pt-2 border-t border-white/5">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/40 block mb-3">
              Key Details
            </span>
            <ul className="space-y-2">
              {analysis.key_details.map((d, i) => (
                <li key={i} className="text-sm font-medium text-white/80 flex gap-3 items-start">
                  <span className="text-indigo-400/50 text-xs mt-0.5">▪</span>
                  <span className="leading-relaxed">{d}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Cultural context */}
        {analysis.cultural_context && (
          <div className="p-4 rounded-xl bg-purple-500/5 border border-purple-500/10 shadow-inner">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-purple-400 text-sm">💡</span>
              <span className="text-[10px] font-bold uppercase tracking-widest text-purple-300">
                Cultural Context
              </span>
            </div>
            <p className="text-sm text-purple-100/70 leading-relaxed font-medium">
              {analysis.cultural_context}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function EditableField({ label, value, isEditing, isEdited, onChange }) {
  return (
    <div className="flex flex-col gap-1.5 p-3 rounded bg-white/[0.02] border border-white/5">
      <span className="text-[8px] font-black uppercase tracking-[0.2em] text-white/20 flex items-center gap-1.5">
        {label}
        {isEdited && (
          <span className="w-1 h-1 rounded-full bg-indigo-400 animate-pulse" />
        )}
      </span>
      {isEditing ? (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-black/40 border border-indigo-500/30 rounded px-2 py-1 text-[11px] font-bold text-indigo-100 outline-none focus:border-indigo-500"
        />
      ) : (
        <p className={`text-[10px] font-black uppercase tracking-wider truncate ${isEdited ? 'text-indigo-400' : 'text-white/70'}`}>
          {value}
        </p>
      )}
    </div>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="rounded bg-black/30 border border-white/10 p-2 min-w-0">
      <div className="text-[8px] font-black uppercase tracking-widest text-white/25">{label}</div>
      <div className="text-[10px] font-bold uppercase text-white/70 truncate">{value}</div>
    </div>
  );
}

function GuidanceRow({ label, value, tone }) {
  const colors = {
    amber: 'text-amber-200 border-amber-500/20 bg-amber-500/5',
    sky: 'text-sky-200 border-sky-500/20 bg-sky-500/5',
    red: 'text-red-200 border-red-500/20 bg-red-500/5',
    emerald: 'text-emerald-200 border-emerald-500/20 bg-emerald-500/5',
  };
  return (
    <div className={`rounded border px-3 py-2 ${colors[tone] || colors.sky}`}>
      <div className="text-[8px] font-black uppercase tracking-widest opacity-60">{label}</div>
      <div className="text-[11px] leading-relaxed font-medium mt-1">{value}</div>
    </div>
  );
}

function ms(value) {
  return Number.isFinite(value) ? `${Math.round(value)} ms` : '--';
}
