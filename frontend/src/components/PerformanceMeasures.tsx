import React from 'react';
import { AlertCircle, CheckCircle2, CircleSlash, Info } from 'lucide-react';

/**
 * TRAFFICINTEL AI - ATSPM Performance Measures
 *
 * Renders a signal performance report so that a measure which could not be
 * computed is as visible as one that could.
 *
 * The two failure states are shown differently on purpose, because they have
 * different remedies:
 *
 *   INSUFFICIENT_DATA  the right inputs exist, there are too few. Wait, or
 *                      widen the window. Shown in amber with n / n-required.
 *   NOT_COMPUTABLE     a required input does not exist at all. Waiting will
 *                      not help; connect something. Shown in slate with the
 *                      missing input named.
 *
 * A dashboard that hid either behind a dash would leave an operator believing
 * the measure was fine.
 */

export interface Measure {
  value: number | null;
  status: 'COMPUTED' | 'INSUFFICIENT_DATA' | 'NOT_COMPUTABLE';
  sample_size: number;
  minimum_samples: number;
  method: string;
  inputs_used: string[];
  explanation: string;
  unit?: string;
  level_of_service?: string;
  [key: string]: any;
}

const STATUS_STYLE = {
  COMPUTED: {
    color: 'var(--its-text-primary)',
    accent: 'var(--its-signal-green)',
    border: 'var(--its-signal-green-border)',
    bg: 'transparent',
    icon: <CheckCircle2 size={13} />,
    label: 'MEASURED',
  },
  INSUFFICIENT_DATA: {
    color: 'var(--its-text-muted)',
    accent: 'var(--its-signal-yellow)',
    border: 'var(--its-signal-yellow-border)',
    bg: 'var(--its-signal-yellow-bg)',
    icon: <AlertCircle size={13} />,
    label: 'INSUFFICIENT DATA',
  },
  NOT_COMPUTABLE: {
    color: 'var(--its-text-muted)',
    accent: 'var(--its-text-muted)',
    border: 'var(--its-border-default)',
    bg: 'var(--its-stale-bg)',
    icon: <CircleSlash size={13} />,
    label: 'NOT COMPUTABLE',
  },
} as const;

export const MeasureCard: React.FC<{ name: string; measure: Measure }> = ({ name, measure }) => {
  const style = STATUS_STYLE[measure.status] ?? STATUS_STYLE.NOT_COMPUTABLE;
  const title = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  return (
    <div
      className="its-card"
      style={{ borderColor: style.border, background: style.bg }}
    >
      <div className="its-card-header">
        <span className="its-card-title">
          <span style={{ color: style.accent, display: 'flex' }}>{style.icon}</span>
          <span>{title}</span>
        </span>
        <span
          className="mono"
          style={{ fontSize: '9px', fontWeight: 700, color: style.accent }}
        >
          {style.label}
        </span>
      </div>

      {measure.status === 'COMPUTED' ? (
        <>
          <div className="mono" style={{ fontSize: 'var(--text-2xl)', fontWeight: 700, lineHeight: 1.1 }}>
            {measure.value}
            {measure.unit && (
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)', marginLeft: '4px' }}>
                {measure.unit}
              </span>
            )}
          </div>

          {measure.level_of_service && (
            <div style={{ marginTop: '6px' }}>
              <span
                className="mono"
                style={{
                  fontSize: 'var(--text-xs)', fontWeight: 700, padding: '2px 9px',
                  borderRadius: 'var(--radius-full)',
                  background: ['A', 'B', 'C'].includes(measure.level_of_service)
                    ? 'var(--its-signal-green-bg)'
                    : measure.level_of_service === 'D'
                      ? 'var(--its-signal-yellow-bg)' : 'var(--its-signal-red-bg)',
                  color: ['A', 'B', 'C'].includes(measure.level_of_service)
                    ? 'var(--its-signal-green)'
                    : measure.level_of_service === 'D'
                      ? 'var(--its-signal-yellow)' : 'var(--its-signal-red)',
                }}
              >
                LOS {measure.level_of_service}
              </span>
            </div>
          )}

          <div
            className="mono"
            style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px' }}
          >
            n = {measure.sample_size}
          </div>
        </>
      ) : (
        <>
          {/* No number at all - not a dash that reads as zero. */}
          <div
            className="mono"
            style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: style.accent }}
          >
            {measure.status === 'INSUFFICIENT_DATA'
              ? `n = ${measure.sample_size} of ${measure.minimum_samples} required`
              : 'REQUIRED INPUT MISSING'}
          </div>

          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '8px', lineHeight: 1.6 }}>
            {measure.explanation}
          </div>
        </>
      )}

      <details style={{ marginTop: '10px' }}>
        <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--its-text-muted)' }}>
          Method & inputs
        </summary>
        <div style={{ fontSize: '10px', color: 'var(--its-text-secondary)', marginTop: '5px', lineHeight: 1.6 }}>
          <div>{measure.method}</div>
          <div className="mono" style={{ marginTop: '4px', color: 'var(--its-text-muted)' }}>
            {(measure.inputs_used ?? []).join(' · ')}
          </div>
          {measure.estimate_basis && (
            <div className="mono" style={{ marginTop: '4px', color: 'var(--its-signal-yellow)' }}>
              {measure.estimate_basis}
            </div>
          )}
          {measure.interval_edge_uncertainty && (
            <div className="mono" style={{ marginTop: '4px', color: 'var(--its-text-muted)' }}>
              EDGE UNCERTAINTY: {measure.interval_edge_uncertainty}
            </div>
          )}
        </div>
      </details>
    </div>
  );
};

export const PerformanceMeasures: React.FC<{ report: any }> = ({ report }) => {
  if (!report) return null;

  const summary = report.summary ?? {};
  const measures = report.measures ?? {};

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div
        style={{
          display: 'flex', gap: '18px', flexWrap: 'wrap', padding: '10px 12px',
          borderRadius: 'var(--radius-sm)', background: 'var(--its-bg-subsurface)',
          fontSize: 'var(--text-2xs)',
        }}
      >
        {[
          ['Computed', summary.computed?.length ?? 0, 'var(--its-signal-green)'],
          ['Insufficient data', summary.insufficient_data?.length ?? 0, 'var(--its-signal-yellow)'],
          ['Not computable', summary.not_computable?.length ?? 0, 'var(--its-text-muted)'],
        ].map(([label, count, color]) => (
          <span key={String(label)} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: String(color) }} />
            <span className="mono" style={{ fontWeight: 700 }}>{String(count)}</span>
            <span style={{ color: 'var(--its-text-muted)' }}>{label}</span>
          </span>
        ))}
      </div>

      {report.note && (
        <div
          style={{
            display: 'flex', gap: '8px', padding: '9px 11px',
            borderRadius: 'var(--radius-sm)', background: 'var(--its-fresh-bg)',
            border: '1px solid var(--its-border-accent)',
            fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.6,
          }}
        >
          <Info size={13} color="var(--its-text-accent)" style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{report.note}</span>
        </div>
      )}

      <div className="grid-3">
        {Object.entries(measures).map(([name, measure]) => (
          <MeasureCard key={name} name={name} measure={measure as Measure} />
        ))}
      </div>
    </div>
  );
};

export const TimeOfDayProfile: React.FC<{ profile: any }> = ({ profile }) => {
  if (!profile) return null;

  const hours: any[] = profile.profile ?? [];
  const values = hours.map(h => h.mean_vehicle_count).filter((v): v is number => v !== null);
  const peak = values.length ? Math.max(...values) : 0;

  return (
    <div className="its-card">
      <div className="its-card-header">
        <span className="its-card-title">Time-of-Day Profile</span>
        <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
          {profile.hours_with_data}/24 HOURS WITH SAMPLES
        </span>
      </div>

      {profile.total_samples === 0 ? (
        <div className="mono" style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}>
          NO STORED TELEMETRY FOR THIS WINDOW
        </div>
      ) : (
        <>
          <div
            style={{
              display: 'grid', gridTemplateColumns: 'repeat(24, 1fr)',
              gap: '2px', alignItems: 'end', height: '120px', marginBottom: '6px',
            }}
          >
            {hours.map(hour => {
              const hasData = hour.sample_size > 0;
              const height = hasData && peak > 0
                ? Math.max(4, (hour.mean_vehicle_count / peak) * 100)
                : 0;
              return (
                <div
                  key={hour.hour_utc}
                  title={
                    hasData
                      ? `${hour.hour_utc}:00 UTC — ${hour.mean_vehicle_count} veh (n=${hour.sample_size})`
                      : `${hour.hour_utc}:00 UTC — no samples stored`
                  }
                  style={{
                    height: hasData ? `${height}%` : '100%',
                    // An hour with no samples is drawn as a hatched void, not a
                    // zero-height bar that reads as "no traffic".
                    background: hasData ? 'var(--its-text-accent)' : 'transparent',
                    backgroundImage: hasData
                      ? undefined
                      : 'repeating-linear-gradient(45deg, var(--its-border-subtle), var(--its-border-subtle) 2px, transparent 2px, transparent 5px)',
                    borderRadius: '2px 2px 0 0',
                    minHeight: '4px',
                  }}
                />
              );
            })}
          </div>

          <div
            className="mono"
            style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: 'var(--its-text-muted)' }}
          >
            <span>00 UTC</span><span>06</span><span>12</span><span>18</span><span>23</span>
          </div>

          <div style={{ fontSize: '10px', color: 'var(--its-text-secondary)', marginTop: '10px', lineHeight: 1.6 }}>
            Hatched hours have no stored samples. {profile.explanation}
          </div>
        </>
      )}
    </div>
  );
};
