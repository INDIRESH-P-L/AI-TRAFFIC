import React from 'react';
import { Activity, AlertTriangle, HelpCircle, ShieldOff } from 'lucide-react';
import { formatTimestamp } from '../../lib/quality';

/**
 * TRAFFICINTEL AI - Anomaly Detection Panel
 *
 * Renders the result of GET /intelligence/anomalies/{id} and nothing else: no
 * value on this panel is computed in the browser.
 *
 * The rule the layout serves: a metric that could not be evaluated must never
 * look like a metric that was evaluated and found normal. "No anomaly" is only
 * ever printed next to the metrics it applies to; every metric the detector
 * could not test is listed by name, with the reason, in the same place.
 *
 * Confidence is shown as a percentage with a hard ceiling of ">99.99%".
 * Rounding 0.999996 to "100.00%" would print certainty the statistics do not
 * support.
 */

type Status = 'MEASURED_ANOMALY' | 'NO_ANOMALY' | 'INSUFFICIENT_DATA' | 'NOT_COMPUTABLE' | string;

export interface AnomalyResult {
  status: Status;
  detail: string;
  intersection_name?: string;
  as_of?: string;
  metrics_evaluated?: string[];
  metrics_not_evaluated?: string[];
  rows_excluded_as_not_measurements?: number;
  metrics: any[];
  method?: string;
  method_version?: string;
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return '--';
  if (value >= 0.9999) return '>99.99%';
  return `${(value * 100).toFixed(2)}%`;
}

const statusLook = (status: Status) => {
  switch (status) {
    case 'MEASURED_ANOMALY':
      return { color: 'var(--its-signal-red)', label: 'MEASURED ANOMALY', Icon: AlertTriangle };
    case 'NO_ANOMALY':
      return { color: 'var(--its-signal-green)', label: 'NO ANOMALY', Icon: Activity };
    case 'INSUFFICIENT_DATA':
      return { color: 'var(--its-text-muted)', label: 'INSUFFICIENT DATA', Icon: HelpCircle };
    default:
      return { color: 'var(--its-text-muted)', label: 'NOT COMPUTABLE', Icon: ShieldOff };
  }
};

const MetricCard: React.FC<{ metric: any }> = ({ metric }) => {
  const look = statusLook(metric.status);
  const baseline = metric.baseline;
  const evaluated = metric.status === 'MEASURED_ANOMALY' || metric.status === 'NO_ANOMALY';

  return (
    <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '12px', fontWeight: 700, flex: 1 }}>{metric.label}</span>
        <span style={{ fontSize: '10px', fontWeight: 700, color: look.color, letterSpacing: '0.04em' }}>
          {look.label}
        </span>
      </div>

      {!evaluated && metric.reason && (
        <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}>
          {metric.reason}
        </div>
      )}
      <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '5px', lineHeight: 1.6 }}>
        {metric.explanation}
      </div>

      {baseline && (
        <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '7px', lineHeight: 1.6 }}>
          <span className="mono">
            BASELINE {baseline.mode.replace(/_/g, ' ')} · n={baseline.sample_size} · {baseline.mean} ± {baseline.std_dev} {metric.unit}
          </span>
          {baseline.caveat && (
            <div
              style={{
                marginTop: '3px',
                color: baseline.mode === 'RECENT_WINDOW' ? 'var(--its-signal-yellow)' : 'var(--its-text-muted)',
              }}
            >
              {baseline.caveat}
            </div>
          )}
        </div>
      )}

      {metric.status === 'INSUFFICIENT_DATA' && metric.baseline_candidates && (
        <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '5px' }}>
          same time of day: {metric.baseline_candidates.same_time_of_day} · preceding window:{' '}
          {metric.baseline_candidates.recent_window} · required: {metric.minimum_baseline_samples}
        </div>
      )}

      {metric.flagged_points?.length > 0 && (
        <div className="its-table-container" style={{ marginTop: '8px' }}>
          <table className="its-table">
            <thead>
              <tr>
                <th>Recorded</th>
                <th>Value</th>
                <th>Deviation</th>
                <th>Confidence</th>
                <th>Source row</th>
              </tr>
            </thead>
            <tbody>
              {metric.flagged_points.map((point: any) => (
                <tr key={point.source_row_id}>
                  <td className="mono" style={{ fontSize: '10px' }}>{formatTimestamp(point.timestamp)}</td>
                  <td className="mono">
                    {point.value} {metric.unit}
                    <span style={{ color: look.color, marginLeft: '4px', fontSize: '9px' }}>{point.direction}</span>
                  </td>
                  <td className="mono">{point.deviation_std > 0 ? '+' : ''}{point.deviation_std}σ</td>
                  <td className="mono" title={`p = ${point.p_value.toExponential(2)}, df = ${point.degrees_of_freedom}`}>
                    {formatConfidence(point.confidence)}
                  </td>
                  <td className="mono" style={{ fontSize: '9px', color: 'var(--its-text-muted)' }}>
                    {`${point.source_table}#${String(point.source_row_id).slice(0, 8)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {metric.sustained_shift && (
        <div
          style={{
            marginTop: '8px',
            padding: '7px 9px',
            border: '1px solid var(--its-border-subtle)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '10px',
            lineHeight: 1.6,
          }}
        >
          <strong>SUSTAINED SHIFT {metric.sustained_shift.direction}: </strong>
          {metric.sustained_shift.status.replace(/_/g, ' ')}
          {metric.sustained_shift.confidence !== null && metric.sustained_shift.confidence !== undefined && (
            <span className="mono"> · {formatConfidence(metric.sustained_shift.confidence)}</span>
          )}
          <div style={{ color: 'var(--its-text-muted)' }}>{metric.sustained_shift.explanation}</div>
        </div>
      )}

      {evaluated && metric.confidence_basis && metric.status === 'MEASURED_ANOMALY' && (
        <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.6 }}>
          {metric.confidence_basis}
        </div>
      )}
    </div>
  );
};

export const AnomalyPanel: React.FC<{ result: AnomalyResult }> = ({ result }) => {
  const look = statusLook(result.status);
  const Icon = look.Icon;

  return (
    <div className="its-panel">
      <div style={{ display: 'flex', gap: '10px', padding: '14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
        <Icon size={20} style={{ color: look.color, flexShrink: 0, marginTop: '2px' }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '13px', fontWeight: 800, color: look.color, letterSpacing: '0.04em' }}>
            {look.label}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
            {result.detail}
          </div>
          {result.as_of && (
            <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}>
              Evaluated as of {formatTimestamp(result.as_of)}
              {result.rows_excluded_as_not_measurements
                ? ` · ${result.rows_excluded_as_not_measurements} row(s) excluded as INVALID/NO_DATA`
                : ''}
            </div>
          )}
        </div>
      </div>

      {(result.metrics_not_evaluated?.length ?? 0) > 0 && (
        <div
          style={{
            padding: '9px 14px',
            borderBottom: '1px solid var(--its-border-subtle)',
            background: 'var(--its-bg-elevated)',
            fontSize: '10px',
            lineHeight: 1.6,
          }}
        >
          <strong>NOT EVALUATED: </strong>
          {result.metrics_not_evaluated!.join('; ')}. No flag on these is not evidence of normal conditions.
        </div>
      )}

      {result.metrics.map((metric) => (
        <MetricCard key={metric.metric} metric={metric} />
      ))}

      {result.method && (
        <div style={{ padding: '10px 14px', fontSize: '9px', color: 'var(--its-text-muted)', lineHeight: 1.6 }}>
          <strong>METHOD ({result.method_version}): </strong>
          {result.method}
        </div>
      )}
    </div>
  );
};
