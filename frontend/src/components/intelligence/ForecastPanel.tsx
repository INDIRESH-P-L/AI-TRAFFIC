import React from 'react';
import { Ban, FlaskConical, TrendingUp } from 'lucide-react';
import { formatTimestamp } from '../../lib/quality';

/**
 * TRAFFICINTEL AI - Short-Horizon Forecast Panel
 *
 * Renders GET /predictions/forecast/{id}. Three things this panel guarantees,
 * each asserted by the render check:
 *
 *   1. MEASURED and FORECAST never look alike. Observed bins are a solid line;
 *      the forecast is dashed, sits inside its interval band, is stamped
 *      SCENARIO / HYPOTHETICAL, and starts only after a labelled divider.
 *   2. A refusal is never drawn as a line. When the model was fitted and
 *      refused for lack of skill, the panel says which model, what error it
 *      measured, and what persistence achieved - the refusal has a model
 *      behind it and the operator can see it.
 *   3. The stated 95% interval sits beside its measured backtest coverage, so
 *      an operator can see whether "95%" held on this junction's own data.
 */

export interface ForecastResult {
  forecast_status: string;
  refusal_reason?: string | null;
  message: string;
  metric_label?: string;
  unit?: string;
  stamp?: string;
  data_kind?: string;
  bin_minutes?: number;
  history?: any;
  model?: any;
  backtest?: any;
  forecast_points: any[];
  caveats?: string[];
}

const W = 640;
const H = 190;
const PAD = { top: 16, right: 14, bottom: 26, left: 48 };

const ForecastChart: React.FC<{ observed: any[]; points: any[]; unit?: string }> = ({
  observed,
  points,
  unit,
}) => {
  const all = [
    ...observed.map((o) => o.value),
    ...points.flatMap((p) => [p.lower_95, p.upper_95]),
  ];
  if (all.length === 0) return null;

  const minY = Math.min(...all);
  const maxY = Math.max(...all);
  const spanY = maxY - minY || 1;
  const total = observed.length + points.length;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const x = (i: number) => PAD.left + (total <= 1 ? 0 : (i / (total - 1)) * plotW);
  const y = (v: number) => PAD.top + plotH - ((v - minY) / spanY) * plotH;

  const observedPath = observed
    .map((o, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(o.value).toFixed(1)}`)
    .join(' ');

  // The forecast line starts from the last observed point so the eye follows
  // it, but the band and dashes make clear where measurement stops.
  const originIndex = observed.length - 1;
  const forecastPath = points.length && observed.length
    ? [
        `M${x(originIndex).toFixed(1)},${y(observed[originIndex].value).toFixed(1)}`,
        ...points.map((p, i) => `L${x(observed.length + i).toFixed(1)},${y(p.value).toFixed(1)}`),
      ].join(' ')
    : '';

  const band = points.length
    ? [
        ...points.map((p, i) => `${x(observed.length + i).toFixed(1)},${y(p.upper_95).toFixed(1)}`),
        ...[...points].reverse().map((p, i) =>
          `${x(observed.length + points.length - 1 - i).toFixed(1)},${y(p.lower_95).toFixed(1)}`,
        ),
      ].join(' ')
    : '';

  const dividerX = observed.length ? x(originIndex) : PAD.left;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Observed bins followed by model forecast with 95% interval"
      style={{ display: 'block', maxWidth: `${W}px` }}
    >
      <text x={PAD.left - 6} y={PAD.top + 4} textAnchor="end" fontSize="9" fill="var(--its-text-muted)">
        {Math.round(maxY)}
      </text>
      <text x={PAD.left - 6} y={PAD.top + plotH} textAnchor="end" fontSize="9" fill="var(--its-text-muted)">
        {Math.round(minY)}
      </text>
      <text x={PAD.left - 6} y={PAD.top + plotH / 2} textAnchor="end" fontSize="9" fill="var(--its-text-muted)">
        {unit}
      </text>

      {band && <polygon points={band} fill="var(--its-text-accent)" opacity="0.15" />}

      <path d={observedPath} fill="none" stroke="var(--its-text-primary)" strokeWidth="1.8" />
      {observed.map((o, i) => (
        <circle key={o.bin_start} cx={x(i)} cy={y(o.value)} r="2" fill="var(--its-text-primary)" />
      ))}

      {forecastPath && (
        <path
          d={forecastPath}
          fill="none"
          stroke="var(--its-text-accent)"
          strokeWidth="1.8"
          strokeDasharray="5 4"
          data-kind="MODEL_FORECAST"
        />
      )}

      <line
        x1={dividerX}
        y1={PAD.top - 4}
        x2={dividerX}
        y2={PAD.top + plotH + 4}
        stroke="var(--its-border-default)"
        strokeDasharray="2 3"
      />
      <text x={dividerX - 4} y={H - 8} textAnchor="end" fontSize="9" fill="var(--its-text-muted)">
        MEASURED
      </text>
      {points.length > 0 && (
        <text x={dividerX + 4} y={H - 8} fontSize="9" fill="var(--its-text-accent)">
          FORECAST (NOT OBSERVED)
        </text>
      )}
    </svg>
  );
};

export const ForecastPanel: React.FC<{ result: ForecastResult }> = ({ result }) => {
  const available = result.forecast_status === 'FORECAST_AVAILABLE';
  const notComputable = result.forecast_status === 'NOT_COMPUTABLE';
  const history = result.history || {};
  const observed = history.recent_observed_bins || [];
  const backtest = result.backtest;
  const model = result.model;

  const color = available
    ? 'var(--its-text-accent)'
    : 'var(--its-text-muted)';
  const Icon = available ? TrendingUp : Ban;

  return (
    <div className="its-panel">
      <div style={{ display: 'flex', gap: '10px', padding: '14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
        <Icon size={20} style={{ color, flexShrink: 0, marginTop: '2px' }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '13px', fontWeight: 800, color, letterSpacing: '0.04em' }}>
            {available ? 'FORECAST AVAILABLE' : result.forecast_status.replace(/_/g, ' ')}
          </div>
          {!available && result.refusal_reason && (
            <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
              {result.refusal_reason}
            </div>
          )}
          <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
            {result.message}
          </div>
        </div>
      </div>

      {available && (
        <div
          style={{
            display: 'flex',
            gap: '8px',
            alignItems: 'center',
            padding: '8px 14px',
            borderBottom: '1px solid var(--its-border-subtle)',
            background: 'var(--its-bg-elevated)',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            color: 'var(--its-signal-yellow)',
          }}
        >
          <FlaskConical size={13} />
          {result.stamp} · MODEL FORECAST, NOT OBSERVED DATA
        </div>
      )}

      {observed.length > 0 && (
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
          <ForecastChart
            observed={observed}
            points={available ? result.forecast_points : []}
            unit={result.unit}
          />
          {!available && (
            <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}>
              Observed bins only. No forecast line is drawn for a refused forecast.
            </div>
          )}
        </div>
      )}

      {available && result.forecast_points.length > 0 && (
        <div className="its-table-container">
          <table className="its-table">
            <thead>
              <tr>
                <th>Bin starting</th>
                <th>Forecast</th>
                <th>95% interval</th>
              </tr>
            </thead>
            <tbody>
              {result.forecast_points.map((point) => (
                <tr key={point.step}>
                  <td className="mono" style={{ fontSize: '10px' }}>{formatTimestamp(point.bin_start)}</td>
                  <td className="mono">
                    {point.value} {result.unit}
                  </td>
                  <td className="mono">
                    {point.lower_95} – {point.upper_95}
                    {point.clipped_to_physical_bounds && (
                      <span style={{ fontSize: '9px', color: 'var(--its-text-muted)' }}> (clipped to physical bounds)</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {model && (
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)', fontSize: '11px', lineHeight: 1.7 }}>
          <div style={{ fontWeight: 700 }}>
            {available ? 'MODEL' : 'A MODEL WAS FITTED AND MEASURED'}: <span className="mono">{model.order}</span>
          </div>
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
            {model.family} · {model.estimation} · trained on {model.training_bins} bins
          </div>
        </div>
      )}

      {backtest?.selected_order && (
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '18px', fontSize: '11px' }} className="mono">
            <span>
              <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>MODEL MAE </span>
              {backtest.selected_mae}
            </span>
            <span>
              <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>PERSISTENCE MAE </span>
              {backtest.persistence_mae}
            </span>
            <span
              style={{
                color:
                  backtest.skill_vs_persistence !== null &&
                  backtest.skill_vs_persistence >= backtest.minimum_skill_required
                    ? 'var(--its-signal-green)'
                    : 'var(--its-signal-red)',
              }}
            >
              <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>SKILL </span>
              {backtest.skill_vs_persistence === null
                ? '--'
                : `${(backtest.skill_vs_persistence * 100).toFixed(1)}%`}
              <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>
                {' '}(required {(backtest.minimum_skill_required * 100).toFixed(0)}%)
              </span>
            </span>
            <span>
              <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>MEASURED 95% COVERAGE </span>
              {backtest.selected_interval_coverage_95 === null || backtest.selected_interval_coverage_95 === undefined
                ? '--'
                : `${(backtest.selected_interval_coverage_95 * 100).toFixed(0)}%`}
            </span>
          </div>
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.6 }}>
            {backtest.method}. {backtest.origins} origins × {backtest.horizon_bins} bins. Persistence:{' '}
            {backtest.persistence_definition?.toLowerCase()}.
          </div>
        </div>
      )}

      {!notComputable && history.samples !== undefined && (
        <div
          className="mono"
          style={{ padding: '10px 14px', fontSize: '10px', color: 'var(--its-text-muted)', lineHeight: 1.7 }}
        >
          {history.samples} stored samples · {history.bins_filled ?? 0} bins filled
          {history.gap_free_run_bins !== undefined && ` · gap-free run ${history.gap_free_run_bins}`}
          {history.bins_required !== undefined && ` / ${history.bins_required} required`}
          {history.missing_bins_in_history ? ` · ${history.missing_bins_in_history} missing bins (never interpolated)` : ''}
          {history.in_progress_bin_excluded && ' · in-progress bin excluded'}
        </div>
      )}

      {available && result.caveats && (
        <div style={{ padding: '0 14px 12px', fontSize: '10px', color: 'var(--its-text-muted)', lineHeight: 1.7 }}>
          {result.caveats.map((c, i) => (
            <div key={i}>- {c}</div>
          ))}
        </div>
      )}
    </div>
  );
};
