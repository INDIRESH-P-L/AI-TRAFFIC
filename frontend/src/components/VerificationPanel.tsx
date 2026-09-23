import React from 'react';
import { ArrowDown, ArrowUp, Equal, HelpCircle, Minus } from 'lucide-react';

/**
 * TRAFFICINTEL AI - Post-Change Verification
 *
 * Answers "did that actually help?" with an interval rather than an arrow.
 *
 * The failure this panel exists to prevent: an operator makes a change, the
 * mean delay drops by 1.2s, and the console congratulates them. On a metric
 * that swings by 4s minute to minute, that is noise, and an operator who
 * learns to trust it will keep making changes that do nothing.
 *
 * So the headline verdict is driven by the confidence interval, not the
 * difference of means, and NO MEASURABLE CHANGE is presented as a real,
 * legitimate answer - not as a failure of the analysis.
 */

export type Verdict =
  | 'IMPROVED'
  | 'DEGRADED'
  | 'NO_MEASURABLE_CHANGE'
  | 'INSUFFICIENT_DATA'
  | 'MIXED';

interface Comparison {
  metric: string;
  label: string;
  unit: string | null;
  verdict: Verdict;
  before_mean: number | null;
  after_mean: number | null;
  difference: number | null;
  confidence_interval: [number, number] | null;
  confidence_level: number;
  before_sample_size: number;
  after_sample_size: number;
  minimum_samples_per_side: number;
  lower_is_better: boolean;
  explanation: string;
}

export interface VerificationResult {
  status: string;
  overall_verdict?: Verdict;
  headline?: string;
  intersection_name?: string | null;
  before_window?: [string, string];
  after_window?: [string, string];
  before_samples?: number;
  after_samples?: number;
  comparisons?: Comparison[];
  method?: string;
  method_caveats?: string[];
  detail?: string;
  label?: string;
  changed_at?: string;
  command_status?: string;
}

const verdictLook = (verdict: Verdict | undefined) => {
  switch (verdict) {
    case 'IMPROVED':
      return { color: 'var(--its-status-normal)', icon: ArrowDown, label: 'IMPROVED' };
    case 'DEGRADED':
      return { color: 'var(--its-status-critical)', icon: ArrowUp, label: 'DEGRADED' };
    case 'NO_MEASURABLE_CHANGE':
      return { color: 'var(--its-text-secondary)', icon: Equal, label: 'NO MEASURABLE CHANGE' };
    case 'MIXED':
      return { color: 'var(--its-status-warning)', icon: Minus, label: 'MIXED' };
    default:
      return { color: 'var(--its-text-muted)', icon: HelpCircle, label: 'INSUFFICIENT DATA' };
  }
};

const fmt = (value: number | null, unit: string | null): string =>
  value === null ? '--' : `${value.toFixed(1)}${unit ? ` ${unit}` : ''}`;

/**
 * The confidence interval drawn to scale, with zero marked.
 *
 * This is the whole argument in one picture: if the bar straddles the zero
 * line, the data does not distinguish the change from no change, whatever
 * the difference of means happens to be.
 */
const IntervalBar: React.FC<{ comparison: Comparison }> = ({ comparison }) => {
  const ci = comparison.confidence_interval;
  if (!ci) return null;

  const [low, high] = ci;
  const extent = Math.max(Math.abs(low), Math.abs(high)) * 1.25 || 1;
  const toPct = (v: number) => 50 + (v / extent) * 50;

  const spansZero = low <= 0 && high >= 0;
  const color = spansZero
    ? 'var(--its-text-secondary)'
    : comparison.verdict === 'IMPROVED'
      ? 'var(--its-status-normal)'
      : 'var(--its-status-critical)';

  const left = Math.max(toPct(low), 0);
  const right = Math.min(toPct(high), 100);

  return (
    <div style={{ marginTop: '7px' }}>
      <div
        style={{
          position: 'relative',
          height: '18px',
          background: 'var(--its-bg-base)',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-sm)',
        }}
      >
        {/* Zero line - the reference everything is judged against */}
        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: 0,
            bottom: 0,
            width: '1px',
            background: 'var(--its-text-muted)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: `${left}%`,
            width: `${Math.max(right - left, 1.5)}%`,
            top: '5px',
            height: '8px',
            background: color,
            borderRadius: '2px',
            opacity: 0.85,
          }}
          title={`95% confidence interval: ${low.toFixed(2)} to ${high.toFixed(2)}`}
        />
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: '9px',
          color: 'var(--its-text-muted)',
          marginTop: '3px',
        }}
        className="mono"
      >
        <span>{low.toFixed(2)}</span>
        <span style={{ color: spansZero ? 'var(--its-text-secondary)' : 'var(--its-text-muted)' }}>
          {spansZero ? 'interval contains 0' : 'interval excludes 0'}
        </span>
        <span>{high.toFixed(2)}</span>
      </div>
    </div>
  );
};

const ComparisonRow: React.FC<{ comparison: Comparison }> = ({ comparison }) => {
  const look = verdictLook(comparison.verdict);
  const Icon = look.icon;

  return (
    <div style={{ padding: '11px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '11px', fontWeight: 600, flex: 1 }}>
          {comparison.label}
          <span style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginLeft: '6px' }}>
            {comparison.lower_is_better ? '(lower is better)' : '(higher is better)'}
          </span>
        </span>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            fontSize: '10px',
            fontWeight: 700,
            color: look.color,
          }}
        >
          <Icon size={12} />
          {look.label}
        </span>
      </div>

      <div
        style={{
          display: 'flex',
          gap: '18px',
          marginTop: '6px',
          fontSize: '11px',
        }}
        className="mono"
      >
        <span>
          <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>BEFORE </span>
          {fmt(comparison.before_mean, comparison.unit)}
          <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>
            {' '}n={comparison.before_sample_size}
          </span>
        </span>
        <span>
          <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>AFTER </span>
          {fmt(comparison.after_mean, comparison.unit)}
          <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>
            {' '}n={comparison.after_sample_size}
          </span>
        </span>
        <span style={{ color: look.color }}>
          <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>DIFF </span>
          {comparison.difference === null
            ? '--'
            : `${comparison.difference > 0 ? '+' : ''}${comparison.difference.toFixed(2)}`}
        </span>
      </div>

      <IntervalBar comparison={comparison} />

      <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.6 }}>
        {comparison.explanation}
      </div>
    </div>
  );
};

export const VerificationPanel: React.FC<{ result: VerificationResult }> = ({ result }) => {
  // Cases where no comparison was attempted at all get their own treatment,
  // because "we could not measure it" is a different claim from "it did
  // nothing" and must never be rendered in the same style.
  if (result.status !== 'COMPUTED') {
    return (
      <div className="its-panel" style={{ padding: '16px' }}>
        <div
          style={{
            fontSize: '12px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            color: 'var(--its-text-muted)',
          }}
        >
          {(result.status || 'UNAVAILABLE').replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '7px', lineHeight: 1.6 }}>
          {result.detail || 'This change could not be verified against recorded telemetry.'}
        </div>
        {result.overall_verdict === 'INSUFFICIENT_DATA' && (
          <div
            style={{
              fontSize: '10px',
              color: 'var(--its-text-muted)',
              marginTop: '9px',
              paddingTop: '9px',
              borderTop: '1px solid var(--its-border-subtle)',
            }}
          >
            No verdict is offered. Absence of measurement is not evidence of absence of effect.
          </div>
        )}
      </div>
    );
  }

  const look = verdictLook(result.overall_verdict);
  const Icon = look.icon;

  return (
    <div className="its-panel">
      <div
        style={{
          display: 'flex',
          gap: '12px',
          padding: '14px',
          borderBottom: '1px solid var(--its-border-subtle)',
        }}
      >
        <Icon size={22} style={{ color: look.color, flexShrink: 0, marginTop: '2px' }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '13px', fontWeight: 800, color: look.color, letterSpacing: '0.04em' }}>
            {look.label}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
            {result.headline}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '5px' }} className="mono">
            {result.before_samples} samples before / {result.after_samples} after
            {result.intersection_name ? ` - ${result.intersection_name}` : ''}
          </div>
        </div>
      </div>

      {(result.comparisons || []).map((comparison) => (
        <ComparisonRow key={comparison.metric} comparison={comparison} />
      ))}

      {/* The caveats are part of the result, not small print. An operator
          reading a verdict needs to know demand was not controlled for. */}
      {(result.method || result.method_caveats?.length) && (
        <div style={{ padding: '11px 14px', fontSize: '10px', color: 'var(--its-text-muted)', lineHeight: 1.7 }}>
          {result.method && (
            <div style={{ marginBottom: '5px' }}>
              <strong style={{ color: 'var(--its-text-secondary)' }}>METHOD: </strong>
              {result.method}
            </div>
          )}
          {result.method_caveats?.map((caveat, i) => (
            <div key={i} style={{ display: 'flex', gap: '6px' }}>
              <span aria-hidden="true">-</span>
              <span>{caveat}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
