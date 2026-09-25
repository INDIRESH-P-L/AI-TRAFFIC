import React, { useCallback, useEffect, useState } from 'react';
import { Bus, FlaskConical, Send } from 'lucide-react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { SkeletonRows } from '../components/Skeleton';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { TspDecisionsPanel } from '../components/transit/TspDecisionsPanel';
import { formatTimestamp } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Transit Signal Priority
 *
 * States:
 *   LOADING  skeleton rows.
 *   EMPTY    no feed configured -> says exactly that; no bus is ever invented.
 *            Feed configured but no evaluations yet -> says that instead.
 *   ERROR    named failure; a 403 on dispatch names the missing scope.
 *
 * Evaluation defaults to a dry run. Dispatching green extensions is a separate,
 * explicit action requiring signal:command, and goes through the Safety Engine.
 */

export const Transit: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getTransitEvents());
    } catch (e: any) {
      setError(e?.message || 'Transit records could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const evaluate = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.evaluateTransitPriority(dryRun));
      if (!dryRun) await load();
    } catch (e: any) {
      setError(
        e?.message?.includes('403')
          ? 'Dispatching transit priority requires the signal:command scope. A dry run does not.'
          : e?.message || 'Evaluation failed.',
      );
    } finally {
      setBusy(false);
    }
  };

  const events: any[] = data?.events || [];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', gap: '12px', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>Transit Signal Priority (TSP)</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Conditional priority from GTFS-Realtime: late buses only, green extension only, through the Safety Engine.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <StatusBadge status={data?.status || 'TRANSIT_FEED_NOT_CONFIGURED'} />
          <button className="its-btn its-btn-sm" onClick={() => void evaluate(true)} disabled={busy || !data?.feed_configured}>
            <FlaskConical size={13} /> Evaluate (dry run)
          </button>
          <button className="its-btn its-btn-sm its-btn-primary" onClick={() => void evaluate(false)} disabled={busy || !data?.feed_configured}>
            <Send size={13} /> Evaluate and dispatch
          </button>
        </div>
      </div>

      {error && (
        <div className="its-card" style={{ marginBottom: '14px', fontSize: 'var(--text-xs)', color: 'var(--its-signal-red)' }}>{error}</div>
      )}

      {loading && <SkeletonRows rows={5} label="Loading transit priority records" />}

      {!loading && data && !data.feed_configured && (
        <TruthfulEmptyState
          title="TRANSIT FEED NOT CONFIGURED"
          description="No GTFS-Realtime vehicle position feed is configured (GTFS_RT_VEHICLE_POSITIONS_URL). No transit vehicle is tracked, and none is simulated. Configure an agency feed, or push feed bytes from a gateway to POST /api/v1/transit/tsp/evaluate-feed."
          icon={<Bus size={36} />}
        />
      )}

      {busy && <SkeletonRows rows={4} label="Fetching the feed and evaluating each bus" />}
      {!busy && result && <div style={{ marginBottom: '16px' }}><TspDecisionsPanel result={result} /></div>}

      {!loading && data?.feed_configured && events.length === 0 && (
        <div className="its-card" style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>
          The feed is configured, but no bus has been evaluated near a junction yet.
        </div>
      )}

      {events.length > 0 && (
        <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="its-table">
            <thead>
              <tr>
                <th>Recorded</th>
                <th>Route / vehicle</th>
                <th>Delay</th>
                <th>Decision</th>
                <th>Priority</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev: any) => (
                <tr key={ev.id}>
                  <td className="mono" style={{ fontSize: 'var(--text-2xs)' }}>{formatTimestamp(ev.timestamp)}</td>
                  <td>
                    <span style={{ fontWeight: 600 }}>{ev.route_id}</span>{' '}
                    <span className="mono" style={{ fontSize: 'var(--text-2xs)' }}>{ev.vehicle_id}</span>
                  </td>
                  <td className="mono">
                    {ev.details?.delay_known === false ? 'UNKNOWN' : `${ev.delay_seconds}s`}
                  </td>
                  <td style={{ fontSize: 'var(--text-2xs)' }}>
                    <div style={{ fontWeight: 700 }}>{(ev.decision || 'LEGACY RECORD').replace(/_/g, ' ')}</div>
                    <div style={{ color: 'var(--its-text-muted)' }}>{ev.decision_reason}</div>
                  </td>
                  <td style={{ fontSize: 'var(--text-2xs)' }}>
                    {ev.priority_granted ? 'GRANTED' : ev.priority_requested ? 'REQUESTED, NOT GRANTED' : 'NOT REQUESTED'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
