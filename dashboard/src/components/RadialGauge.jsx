import { useMemo } from 'react';

/**
 * RadialGauge — SVG circular gauge with animated fill and glow effect.
 *
 * Used for Distress Meter and Verification Confidence display.
 * Monochrome glassmorphism aesthetic with color-coded thresholds.
 */
export default function RadialGauge({
  value = 0,
  max = 1,
  size = 140,
  strokeWidth = 6,
  label = '',
  sublabel = '',
  color = 'var(--color-verified)',
  thresholds = null, // [{ at: 0.6, color: '...' }, ...]
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.min(value / max, 1);
  const offset = circumference * (1 - pct);

  // Dynamic color based on thresholds
  const activeColor = useMemo(() => {
    if (!thresholds) return color;
    let c = color;
    for (const t of thresholds) {
      if (pct >= t.at) c = t.color;
    }
    return c;
  }, [pct, thresholds, color]);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="transform -rotate-90">
          {/* Track */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--color-glass-border)"
            strokeWidth={strokeWidth}
          />
          {/* Value arc */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={activeColor}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="gauge-ring"
            style={{ filter: `drop-shadow(0 0 6px ${activeColor})` }}
          />
        </svg>
        {/* Center value */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="text-2xl font-semibold tracking-tight font-mono"
            style={{ color: activeColor }}
          >
            {(pct * 100).toFixed(0)}
          </span>
          <span className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-widest">
            %
          </span>
        </div>
      </div>
      {label && (
        <span className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider">
          {label}
        </span>
      )}
      {sublabel && (
        <span className="text-[10px] text-[var(--color-text-muted)]">
          {sublabel}
        </span>
      )}
    </div>
  );
}
