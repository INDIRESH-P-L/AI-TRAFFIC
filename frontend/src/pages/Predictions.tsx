import React, { useCallback, useEffect, useState } from 'react';
import { Cpu, RefreshCw, TrendingUp } from 'lucide-react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { SkeletonRows } from '../components/Skeleton';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { ForecastPanel } from '../components/intelligence/ForecastPanel';

/**
 * TRAFFICINTEL AI - Forecasting
 *
 * This page previously displayed three "production models" with version
 * numbers, validation MAE/RMSE and precision/recall figures. None of those
 * models existed; the numbers were literals in this file. They have been
 * removed. The registry section now renders only what GET /predictions/models
 * returns, and every forecast figure on the page comes from a model fitted to
 * the selected junction's own stored history, with its measured backtest error.
 *
 * States:
 *   LOADING  skeleton rows for the forecast; the registry shows its own state.
 *   EMPTY    no junctions -> TruthfulEmptyState. No registered models -> the
 *            registry says so, and explains that the forecaster below is
 *            fitted on demand rather than registered.
 *   ERROR    named failure with Retry; no stale forecast is left on screen.
 */

const METRIC_OPTIONS = [
  { value: 'flow_rate_vph', label: 'Throughput' },
  { value: 'occupancy_pct', label: 'Occupancy' },
  { value: 'avg_speed_kph', label: 'Average speed' },
];

export const Predictions: React.FC = () => {
  const [intersections, setIntersections] = useState<any[] | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [metric, setMetric] = useState('flow_rate_vph');
  const [modelsData, setModelsData] = useState<any>(null);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const [forecast, setForecast] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getIntersections()
      .then((list: any[]) => {
        if (cancelled) return;
        setIntersections(list);
        if (list.length) setSelectedId((current) => current || list[0].id);
      })
      .catch(() => {
        if (!cancelled) setIntersections([]);
      });
    api
      .getAiModels()
      .then((data: any) => {
        if (!cancelled) setModelsData(data);
      })
      .catch((e: any) => {
        if (!cancelled) setModelsError(e?.message || 'The model registry could not be read.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(async () => {
    if (!selectedId) return;
    setLoading(true);
    setError(null);
    setForecast(null);
    try {
      setForecast(await api.getForecast(selectedId, metric));
    } catch (e: any) {
      setError(e?.message || 'The forecast could not be computed.');
    } finally {
      setLoading(false);
    }
  }, [selectedId, metric]);

  useEffect(() => {
    void load();
  }, [load]);

  const registered: any[] = modelsData?.models || [];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', gap: '12px', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>Traffic Forecasting</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Short-horizon forecasts fitted to each junction's stored history, offered only when
            they measurably beat repeating the last value.
          </p>
        </div>

        {intersections && intersections.length > 0 && (
          <div style={{ display: 'flex', gap: '8px' }}>
            <select className="its-select" value={selectedId} onChange={(e) => setSelectedId(e.target.value)} style={{ width: '220px' }}>
              {intersections.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name} ({i.code})
                </option>
              ))}
            </select>
            <select className="its-select" value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRIC_OPTIONS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Registry: only what the backend actually returns. */}
      <div className="its-card" style={{ marginBottom: '20px' }}>
        <div className="its-card-header">
          <span className="its-card-title">
            <Cpu size={16} />
            <span>Model Registry</span>
          </span>
          <StatusBadge status={modelsError ? 'ERROR' : modelsData?.status || 'UNKNOWN'} />
        </div>
        {modelsError ? (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-status-critical)' }}>{modelsError}</div>
        ) : registered.length === 0 ? (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', lineHeight: 1.6 }}>
            No models are registered. The forecaster below is not a registered model: it fits an
            ARIMA(p,d,0) model to the selected junction's stored history on each request and reports
            that fit's measured backtest error. No accuracy figure is shown for any model that has
            not been evaluated.
          </div>
        ) : (
          <div className="its-table-container">
            <table className="its-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Version</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {registered.map((m) => (
                  <tr key={m.id}>
                    <td>{m.name}</td>
                    <td className="mono">{m.version ?? '--'}</td>
                    <td>{m.status ?? '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <TrendingUp size={16} />
            <span>Forecast: {forecast?.intersection_name || 'Select a junction'}</span>
          </span>
          <button className="its-btn its-btn-sm" onClick={() => void load()} disabled={!selectedId}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>

        {intersections && intersections.length === 0 && (
          <TruthfulEmptyState
            title="NO JUNCTIONS CONFIGURED"
            description="A forecast is fitted to one junction's stored telemetry. Configure a junction and connect a source that reports to it."
            actionText="Configure intersections"
            actionLink="/intersections"
          />
        )}
        {loading && <SkeletonRows rows={5} label="Fitting and backtesting candidate models" />}
        {!loading && error && (
          <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-status-critical)' }}>
            FORECAST UNAVAILABLE - {error}
          </div>
        )}
        {!loading && !error && forecast && <ForecastPanel result={forecast} />}
      </div>
    </div>
  );
};
