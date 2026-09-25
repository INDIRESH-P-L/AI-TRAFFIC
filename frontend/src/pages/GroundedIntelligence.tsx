import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Brain, Radar, RefreshCw, TrendingUp } from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { AnomalyPanel } from '../components/intelligence/AnomalyPanel';
import { ForecastPanel } from '../components/intelligence/ForecastPanel';
import { FusionPanel } from '../components/intelligence/FusionPanel';
import type { RecordOutcome } from '../components/intelligence/FusionPanel';

/**
 * TRAFFICINTEL AI - Grounded Intelligence
 *
 * Anomalies, short-horizon forecasts and corroborated incident detection for
 * one junction, all computed server-side from stored telemetry.
 *
 * States (per tab):
 *   LOADING  skeleton rows; no status word, no number.
 *   EMPTY    no junctions -> TruthfulEmptyState linking to setup. A junction
 *            with no telemetry is not an empty state here: each panel renders
 *            the backend's NOT_COMPUTABLE / INSUFFICIENT_DATA verdict with its
 *            reason, because "nothing was measured" is itself the finding.
 *   ERROR    the request failure is named with a Retry; the previous result is
 *            cleared rather than left on screen looking current.
 */

type Tab = 'ANOMALIES' | 'FORECAST' | 'FUSION';

const METRIC_OPTIONS = [
  { value: 'flow_rate_vph', label: 'Throughput' },
  { value: 'occupancy_pct', label: 'Occupancy' },
  { value: 'avg_speed_kph', label: 'Average speed' },
];

export const GroundedIntelligence: React.FC = () => {
  const [junctions, setJunctions] = useState<any[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [junctionId, setJunctionId] = useState('');
  const [tab, setTab] = useState<Tab>('ANOMALIES');
  const [metric, setMetric] = useState('flow_rate_vph');

  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [recording, setRecording] = useState(false);
  const [recordOutcome, setRecordOutcome] = useState<RecordOutcome | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getIntersections()
      .then((list: any[]) => {
        if (cancelled) return;
        setJunctions(list);
        if (list.length) setJunctionId((current) => current || list[0].id);
      })
      .catch((e: any) => {
        if (!cancelled) setListError(e?.message || 'Junctions could not be loaded.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(async () => {
    if (!junctionId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setRecordOutcome(null);
    setRecordError(null);
    try {
      if (tab === 'ANOMALIES') setResult(await api.getAnomalies(junctionId));
      else if (tab === 'FORECAST') setResult(await api.getForecast(junctionId, metric));
      else setResult(await api.getIncidentFusion(junctionId));
    } catch (e: any) {
      setError(e?.message || 'The analysis could not be retrieved.');
    } finally {
      setLoading(false);
    }
  }, [junctionId, tab, metric]);

  useEffect(() => {
    void load();
  }, [load]);

  const record = async () => {
    setRecording(true);
    setRecordError(null);
    try {
      const outcome = await api.recordFusionIncidents(junctionId);
      setRecordOutcome(outcome);
    } catch (e: any) {
      setRecordError(
        e?.message?.includes('403')
          ? 'Your role cannot file incidents (incident:write). Ask an operator to record it.'
          : e?.message || 'Recording failed; nothing was filed.',
      );
    } finally {
      setRecording(false);
    }
  };

  const tabButton = (id: Tab, label: string, Icon: React.ElementType) => (
    <button className={`its-tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
      <Icon size={13} /> {label}
    </button>
  );

  return (
    <div className="its-page">
      <div className="its-page-header">
        <div>
          <h1 className="its-page-title">
            <Brain size={18} /> Grounded Intelligence
          </h1>
          <p className="its-page-subtitle">
            Anomalies, forecasts and corroborated incidents, computed only from telemetry this
            platform stored - with the reason whenever a result cannot be produced.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <select
            className="its-select"
            value={junctionId}
            onChange={(e) => setJunctionId(e.target.value)}
            disabled={!junctions?.length}
          >
            {!junctions?.length && <option value="">No junctions</option>}
            {junctions?.map((j) => (
              <option key={j.id} value={j.id}>
                {j.name}
              </option>
            ))}
          </select>
          {tab === 'FORECAST' && (
            <select className="its-select" value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRIC_OPTIONS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          )}
          <button className="its-btn its-btn-sm" onClick={() => void load()} disabled={!junctionId}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="its-tabs" style={{ marginBottom: '14px' }}>
        {tabButton('ANOMALIES', 'Anomalies', Activity)}
        {tabButton('FORECAST', 'Forecast', TrendingUp)}
        {tabButton('FUSION', 'Incident Fusion', Radar)}
      </div>

      {listError && (
        <div className="its-panel" style={{ padding: '14px', fontSize: '11px', color: 'var(--its-status-critical)' }}>
          {listError}
        </div>
      )}

      {!listError && junctions && junctions.length === 0 && (
        <TruthfulEmptyState
          title="NO JUNCTIONS CONFIGURED"
          description="Every analysis on this page runs over one junction's stored telemetry. Configure a junction and connect a source that reports to it."
          actionText="Configure intersections"
          actionLink="/intersections"
        />
      )}

      {loading && <SkeletonRows rows={6} label="Analysing stored telemetry" />}

      {!loading && error && (
        <div className="its-panel" style={{ padding: '18px' }}>
          <div style={{ color: 'var(--its-status-critical)', fontSize: '12px', fontWeight: 700 }}>
            ANALYSIS UNAVAILABLE
          </div>
          <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '6px' }}>
            {error} No previous result is shown, because it may no longer be current.
          </div>
          <button className="its-btn its-btn-sm" style={{ marginTop: '12px' }} onClick={() => void load()}>
            <RefreshCw size={13} /> Retry
          </button>
        </div>
      )}

      {!loading && !error && result && tab === 'ANOMALIES' && <AnomalyPanel result={result} />}
      {!loading && !error && result && tab === 'FORECAST' && <ForecastPanel result={result} />}
      {!loading && !error && result && tab === 'FUSION' && (
        <FusionPanel
          result={result}
          onRecord={() => void record()}
          recording={recording}
          recordOutcome={recordOutcome}
          recordError={recordError}
        />
      )}
    </div>
  );
};
