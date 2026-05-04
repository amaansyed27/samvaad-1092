import { useState, useCallback } from 'react';

/**
 * AnalysisCard — Displays AND allows editing of LLM analysis results.
 *
 * Theme 12 Compliance: Human-in-the-Loop — Agents can review and correct
 * AI-generated analysis before dispatch. Corrections are captured as
 * "learning signals" for continuous system improvement.
 *
 * Features:
 *   - Editable emergency type, severity, location, sentiment
 *   - Visual diff highlighting when edited
 *   - One-click save that sends corrections to backend
 */
export default function AnalysisCard({ analysis, sentiment, language, onAgentEdit }) {
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
      <div className="glass-card p-5 flex flex-col items-center justify-center h-full gap-3">
        <div className="w-10 h-10 rounded-xl bg-[rgba(139,92,246,0.08)] flex items-center justify-center">
          <span className="text-xl">🧠</span>
        </div>
        <span className="text-sm text-[var(--color-text-muted)]">
          Awaiting analysis…
        </span>
        <p className="text-[10px] text-[var(--color-text-muted)] text-center max-w-[200px]">
          Send a transcript or start recording to begin the verification pipeline.
        </p>
      </div>
    );
  }

  const severityColor = {
    critical: 'var(--color-critical)',
    high: 'var(--color-warning)',
    medium: 'var(--color-analyzing)',
    low: 'var(--color-verified)',
  }[getField('severity')?.toLowerCase()] || 'var(--color-text-secondary)';

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <div className="glass-card p-5 space-y-4 animate-slide-up overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
          Emergency Analysis
        </h3>
        <div className="flex items-center gap-2">
          <span
            className="status-badge"
            style={{
              background: `${severityColor}18`,
              color: severityColor,
            }}
          >
            {getField('severity')?.toUpperCase() || 'UNKNOWN'}
          </span>
          {!isEditing ? (
            <button
              onClick={() => setIsEditing(true)}
              className="px-2.5 py-1 rounded-md text-[10px] font-semibold uppercase tracking-wider transition-all duration-200
                hover:scale-[1.03] active:scale-[0.97]"
              style={{
                background: 'rgba(99, 102, 241, 0.08)',
                color: 'var(--color-listening)',
                border: '1px solid rgba(99, 102, 241, 0.15)',
              }}
            >
              ✏ Edit
            </button>
          ) : (
            <div className="flex items-center gap-1">
              {hasEdits && (
                <button
                  onClick={handleSave}
                  className="px-2.5 py-1 rounded-md text-[10px] font-semibold uppercase tracking-wider transition-all duration-200
                    hover:scale-[1.03] active:scale-[0.97]"
                  style={{
                    background: saved ? 'rgba(45, 212, 160, 0.12)' : 'rgba(99, 102, 241, 0.12)',
                    color: saved ? 'var(--color-verified)' : 'var(--color-listening)',
                    border: `1px solid ${saved ? 'rgba(45, 212, 160, 0.2)' : 'rgba(99, 102, 241, 0.2)'}`,
                  }}
                >
                  {saved ? '✓ Saved' : '⬆ Save'}
                </button>
              )}
              <button
                onClick={handleCancel}
                className="px-2.5 py-1 rounded-md text-[10px] font-semibold uppercase tracking-wider transition-all duration-200
                  hover:scale-[1.03] active:scale-[0.97]"
                style={{
                  background: 'rgba(239, 68, 68, 0.08)',
                  color: 'var(--color-critical)',
                  border: '1px solid rgba(239, 68, 68, 0.15)',
                }}
              >
                ✗ Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Agent edit banner */}
      {isEditing && (
        <div className="p-2.5 rounded-lg bg-[rgba(99,102,241,0.06)] border border-[rgba(99,102,241,0.12)] animate-fade-in">
          <p className="text-[10px] text-[var(--color-listening)] uppercase tracking-wider">
            ✏ Editing Mode — Corrections become learning signals
          </p>
        </div>
      )}

      {/* Grid */}
      <div className="grid grid-cols-2 gap-3">
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
          label="Language"
          value={getField('language')}
          isEditing={isEditing}
          isEdited={edits.language !== undefined}
          onChange={(v) => handleEdit('language', v)}
        />
      </div>

      {/* Severity selector when editing */}
      {isEditing && (
        <div className="space-y-1.5">
          <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
            Severity
          </span>
          <div className="flex gap-1.5">
            {['low', 'medium', 'high', 'critical'].map((level) => {
              const colors = {
                low: 'var(--color-verified)',
                medium: 'var(--color-analyzing)',
                high: 'var(--color-warning)',
                critical: 'var(--color-critical)',
              };
              const isActive = getField('severity')?.toLowerCase() === level;
              return (
                <button
                  key={level}
                  onClick={() => handleEdit('severity', level)}
                  className="px-3 py-1 rounded-md text-[10px] font-semibold uppercase tracking-wider transition-all duration-200"
                  style={{
                    background: isActive ? `${colors[level]}20` : 'transparent',
                    color: isActive ? colors[level] : 'var(--color-text-muted)',
                    border: `1px solid ${isActive ? `${colors[level]}40` : 'var(--color-glass-border)'}`,
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
        <div>
          <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
            Key Details
          </span>
          <ul className="mt-1.5 space-y-1">
            {analysis.key_details.map((d, i) => (
              <li key={i} className="text-xs text-[var(--color-text-secondary)] flex gap-2">
                <span className="text-[var(--color-text-muted)]">•</span>
                {d}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Cultural context */}
      {analysis.cultural_context && (
        <div className="p-3 rounded-lg bg-[rgba(139,92,246,0.06)] border border-[rgba(139,92,246,0.12)]">
          <span className="text-[10px] uppercase tracking-wider text-[var(--color-analyzing)]">
            Cultural Context
          </span>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)] leading-relaxed">
            {analysis.cultural_context}
          </p>
        </div>
      )}
    </div>
  );
}


/**
 * EditableField — Inline editable info block with visual diff.
 */
function EditableField({ label, value, isEditing, isEdited, onChange }) {
  return (
    <div className="space-y-0.5">
      <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
        {label}
        {isEdited && (
          <span className="ml-1 text-[var(--color-listening)]">•</span>
        )}
      </span>
      {isEditing ? (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-2 py-1 rounded text-sm bg-[var(--color-elevated)] border transition-colors
            text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-listening)]"
          style={{
            borderColor: isEdited ? 'rgba(99, 102, 241, 0.3)' : 'var(--color-glass-border)',
          }}
        />
      ) : (
        <p className={`text-sm capitalize ${isEdited ? 'text-[var(--color-listening)]' : 'text-[var(--color-text-primary)]'}`}>
          {value}
        </p>
      )}
    </div>
  );
}
