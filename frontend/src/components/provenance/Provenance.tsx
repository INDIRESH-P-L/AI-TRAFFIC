import React from 'react';
import type { Provenance, QualityState, QualityThresholds } from '../../lib/quality';
import {
  DEFAULT_THRESHOLDS,
  formatAge,
  formatSource,
  formatTimestamp,
  normalizeQuality,
  qualityAppearance,
  qualityForAge,
} from '../../lib/quality';
import { useTickingAge } from '../../hooks/useTickingAge';

/**
 * Provenance primitives.
 *
 * Invariant 2 of this platform says every number on screen carries its source,
 * its timestamp and its data-quality state. These components are how that rule
 * is kept in practice rather than in principle: `MeasuredValue` is the only
 * sanctioned way to render a telemetry number, and it cannot be used without
 * supplying provenance.
 *
 * A missing value renders as its truthful absence ("NO DATA"), never as zero.
 */

// ---------------------------------------------------------------------------
// QualityDot - the smallest indicator, for dense tables and map legends
// ---------------------------------------------------------------------------

export const QualityDot: React.FC<{
  state: QualityState;
  size?: number;
  title?: string;
}> = ({ state, size = 8, title }) => {
  const appearance = qualityAppearance(state);
  return (
    <span
      role="img"
      aria-label={`Data quality: ${appearance.label}`}
      title={title ?? `${appearance.label} — ${appearance.meaning}`}
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        background: appearance.color,
        border: `1px solid ${appearance.border}`,
        flexShrink: 0,
      }}
    />
  );
};

// ---------------------------------------------------------------------------
// DataAge - a live counter that keeps ticking while the panel is open
// ---------------------------------------------------------------------------

export const DataAge: React.FC<{
  observedAt: string | null | undefined;
  fallbackAgeSec?: number | null;
  thresholds?: QualityThresholds;
  showState?: boolean;
}> = ({ observedAt, fallbackAgeSec = null, thresholds = DEFAULT_THRESHOLDS, showState = false }) => {
  const age = useTickingAge(observedAt, fallbackAgeSec);
  const state = qualityForAge(age, thresholds);
  const appearance = qualityAppearance(state);

  return (
    <span
      className="mono"
      style={{ color: appearance.color, fontSize: 'var(--text-2xs)', whiteSpace: 'nowrap' }}
      title={`Observed at ${formatTimestamp(observedAt)}`}
    >
      {formatAge(age)}
      {showState && ` · ${appearance.label}`}
    </span>
  );
};

// ---------------------------------------------------------------------------
// ProvenanceChip - state + age in one compact pill
// ---------------------------------------------------------------------------

export const ProvenanceChip: React.FC<{
  provenance: Provenance | null | undefined;
  thresholds?: QualityThresholds;
  compact?: boolean;
}> = ({ provenance, thresholds = DEFAULT_THRESHOLDS, compact = false }) => {
  const age = useTickingAge(provenance?.observed_at, provenance?.age_sec ?? null);
  // With no timestamp there is nothing to age; fall back to the reported state.
  const state = provenance?.observed_at
    ? qualityForAge(age, thresholds)
    : normalizeQuality(provenance?.state);
  const appearance = qualityAppearance(state);

  return (
    <span
      className="provenance-chip"
      title={[
        `${appearance.label} — ${appearance.meaning}`,
        `Source: ${formatSource(provenance?.source)}`,
        `Observed: ${formatTimestamp(provenance?.observed_at)}`,
      ].join('\n')}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        padding: compact ? '1px 6px' : '2px 8px',
        borderRadius: 'var(--radius-full)',
        background: appearance.background,
        border: `1px solid ${appearance.border}`,
        color: appearance.color,
        fontSize: 'var(--text-2xs)',
        fontFamily: 'var(--font-mono)',
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      <QualityDot state={state} size={6} title="" />
      <span>{appearance.label}</span>
      {provenance?.observed_at && (
        <>
          <span aria-hidden="true" style={{ opacity: 0.5 }}>·</span>
          <span>{formatAge(age)}</span>
        </>
      )}
    </span>
  );
};

// ---------------------------------------------------------------------------
// ProvenanceCard - the full disclosure, for hover cards and drawers
// ---------------------------------------------------------------------------

export const ProvenanceCard: React.FC<{
  provenance: Provenance | null | undefined;
  thresholds?: QualityThresholds;
  title?: string;
}> = ({ provenance, thresholds = DEFAULT_THRESHOLDS, title = 'Provenance' }) => {
  const age = useTickingAge(provenance?.observed_at, provenance?.age_sec ?? null);
  const state = provenance?.observed_at
    ? qualityForAge(age, thresholds)
    : normalizeQuality(provenance?.state);
  const appearance = qualityAppearance(state);

  const rows: Array<[string, React.ReactNode]> = [
    ['Quality', <span style={{ color: appearance.color, fontWeight: 700 }}>{appearance.label}</span>],
    ['Source', formatSource(provenance?.source)],
    ['Observed', formatTimestamp(provenance?.observed_at)],
    ['Age', formatAge(age)],
  ];

  return (
    <div
      style={{
        border: `1px solid ${appearance.border}`,
        borderRadius: 'var(--radius-md)',
        background: 'var(--its-bg-surface)',
        padding: '10px 12px',
        minWidth: '240px',
      }}
    >
      <div
        style={{
          fontSize: 'var(--text-2xs)',
          fontWeight: 700,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: 'var(--its-text-muted)',
          marginBottom: '8px',
        }}
      >
        {title}
      </div>

      {rows.map(([label, value]) => (
        <div
          key={label}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: '14px',
            fontSize: 'var(--text-2xs)',
            marginBottom: '4px',
          }}
        >
          <span style={{ color: 'var(--its-text-muted)' }}>{label}</span>
          <span className="mono" style={{ color: 'var(--its-text-primary)', textAlign: 'right' }}>
            {value}
          </span>
        </div>
      ))}

      <div
        style={{
          marginTop: '8px',
          paddingTop: '8px',
          borderTop: '1px solid var(--its-border-subtle)',
          fontSize: 'var(--text-2xs)',
          color: 'var(--its-text-secondary)',
          lineHeight: 1.5,
        }}
      >
        {appearance.meaning}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// MeasuredValue - a telemetry number that cannot be rendered without provenance
// ---------------------------------------------------------------------------

export const MeasuredValue: React.FC<{
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  provenance?: Provenance | null;
  thresholds?: QualityThresholds;
  /** Shown when the value is null — say why it is absent, never print 0. */
  emptyText?: string;
  precision?: number;
}> = ({
  label,
  value,
  unit,
  provenance,
  thresholds = DEFAULT_THRESHOLDS,
  emptyText = 'NO DATA',
  precision,
}) => {
  const isAbsent = value === null || value === undefined || value === '';
  const display = isAbsent
    ? emptyText
    : typeof value === 'number' && precision !== undefined
      ? value.toFixed(precision)
      : String(value);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', minWidth: 0 }}>
      <div
        style={{
          fontSize: 'var(--text-2xs)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          color: 'var(--its-text-muted)',
          fontWeight: 600,
        }}
      >
        {label}
      </div>

      <div
        className="mono"
        style={{
          fontSize: 'var(--text-md)',
          fontWeight: 700,
          color: isAbsent ? 'var(--its-text-muted)' : 'var(--its-text-primary)',
          lineHeight: 1.2,
        }}
      >
        {display}
        {!isAbsent && unit && (
          <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginLeft: '3px' }}>
            {unit}
          </span>
        )}
      </div>

      {/* Provenance travels with the number, present or absent. */}
      <ProvenanceChip provenance={provenance} thresholds={thresholds} compact />
    </div>
  );
};
