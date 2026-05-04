/**
 * AnalysisCard — Displays the LLM analysis result in a structured card.
 * Shows emergency type, severity, location hints, and cultural context.
 */
export default function AnalysisCard({ analysis, sentiment, language }) {
  if (!analysis) {
    return (
      <div className="glass-card p-5 flex items-center justify-center h-full">
        <span className="text-sm text-[var(--color-text-muted)]">
          Awaiting analysis…
        </span>
      </div>
    );
  }

  const severityColor = {
    critical: 'var(--color-critical)',
    high: 'var(--color-warning)',
    medium: 'var(--color-analyzing)',
    low: 'var(--color-verified)',
  }[analysis.severity] || 'var(--color-text-secondary)';

  return (
    <div className="glass-card p-5 space-y-4 animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
          Emergency Analysis
        </h3>
        <span className="status-badge" style={{ background: `${severityColor}18`, color: severityColor }}>
          {analysis.severity?.toUpperCase() || 'UNKNOWN'}
        </span>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-2 gap-3">
        <InfoBlock label="Type" value={analysis.emergency_type || '—'} />
        <InfoBlock label="Sentiment" value={sentiment || analysis.sentiment || '—'} />
        <InfoBlock label="Location" value={analysis.location_hint || 'Not detected'} />
        <InfoBlock label="Language" value={language || '—'} />
      </div>

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

function InfoBlock({ label, value }) {
  return (
    <div className="space-y-0.5">
      <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
        {label}
      </span>
      <p className="text-sm text-[var(--color-text-primary)] capitalize">
        {value}
      </p>
    </div>
  );
}
