import React, { useCallback, useEffect, useState } from 'react';
import { GitCommitHorizontal, RefreshCw, Waves } from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { StringlineDiagram } from '../components/StringlineDiagram';
import type { StringlineResult } from '../components/StringlineDiagram';
import { formatTimestamp } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Corridor Stringline
 *
 * A time-space diagram built from what the controllers were OBSERVED doing,
 * rather than from the timing plan they were given. The difference is the
 * point of the page: a plan that says "coordinated" and a corridor that is
 * observably not coordinated look identical on every other screen.
 *
 * States:
 *   LOADING  skeleton, no axes drawn.
 *   EMPTY    corridor with fewer than two junctions -> NOT_COMPUTABLE, said
 *            in words. Corridor with junctions but no polled state in the
 *            window -> INSUFFICIENT_DATA, and the diagram is not drawn at
 *            all rather than drawn empty.
 *   ERROR    the request failure is named; nothing is drawn.
 */

interface CorridorSummary {
  id: string;
  name: string;
  coordination_mode?: string | null;
  intersection_count?: number;
}

const SEGMENT_STATUS_LABEL: Record<string, string> = {
  COMPUTED: 'MEASURED',
  OFFSET_BELOW_MEASUREMENT_RESOLUTION: 'BELOW RESOLUTION',
  IMPLIED_SPEED_IMPLAUSIBLE: 'IMPLAUSIBLE - NOT REPORTED',
  INSUFFICIENT_DATA: 'INSUFFICIENT DATA',
  NOT_COMPUTABLE: 'NOT COMPUTABLE',
};

export const Stringline: React.FC = () => {
  const [corridors, setCorridors] = useState<CorridorSummary[] | null>(null);
  const [corridorId, setCorridorId] = useState('');
  const [minutes, setMinutes] = useState(15);

  const [result, setResult] = useState<StringlineResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.getCorridors();
        if (cancelled) return;
        const list: CorridorSummary[] = Array.isArray(data)
          ? (data as CorridorSummary[])
          : ((data as { corridors?: CorridorSummary[] }).corridors ?? []);
        setCorridors(list);
        if (list.length) setCorridorId((current) => current || list[0].id);
      } catch (e: any) {
        if (!cancelled) setListError(e?.message || 'Corridors could not be loaded.');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(async () => {
    if (!corridorId) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.getStringline(corridorId, minutes));
    } catch (e: any) {
      setResult(null);
      setError(e?.message || 'The stringline could not be built.');
    } finally {
      setLoading(false);
    }
  }, [corridorId, minutes]);

  useEffect(() => {
    void load();
  }, [load]);

  const progression = result?.progression;

  return (
    <div className="its-page">
      <div className="its-page-header">
        <div>
          <h1 className="its-page-title">
            <Waves size={18} /> Corridor Stringline
          </h1>
          <p className="its-page-subtitle">
            Observed green intervals plotted against distance and time - what the corridor was
            seen doing, not what its timing plan says it should do.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <select
            className="its-select"
            value={corridorId}
            onChange={(e) => setCorridorId(e.target.value)}
            disabled={!corridors?.length}
          >
            {!corridors?.length && <option value="">No corridors</option>}
            {corridors?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            className="its-select"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
          >
            <option value={5}>Last 5 min</option>
            <option value={15}>Last 15 min</option>
            <option value={60}>Last 60 min</option>
            <option value={240}>Last 4 h</option>
          </select>
          <button className="its-btn its-btn-sm" onClick={() => void load()} disabled={!corridorId}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {listError && (
        <div className="its-panel" style={{ padding: '14px', fontSize: '11px', color: 'var(--its-status-critical)' }}>
          {listError}
        </div>
      )}

      {!listError && corridors && corridors.length === 0 && (
        <TruthfulEmptyState
          title="NO CORRIDORS CONFIGURED"
          description="A stringline plots junctions along a corridor. Define a corridor of at least two junctions before a time-space diagram can be drawn."
          actionText="Configure corridors"
          actionLink="/corridors"
        />
      )}

      {loading && <SkeletonRows rows={6} label="Reading observed signal state" />}

      {!loading && error && (
        <div className="its-panel" style={{ padding: '18px' }}>
          <div style={{ color: 'var(--its-status-critical)', fontSize: '12px', fontWeight: 700 }}>
            STRINGLINE UNAVAILABLE
          </div>
          <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '6px' }}>
            {error}
          </div>
          <button className="its-btn its-btn-sm" style={{ marginTop: '12px' }} onClick={() => void load()}>
            <RefreshCw size={13} /> Retry
          </button>
        </div>
      )}

      {!loading && !error && result && result.status !== 'COMPUTED' && (
        <div className="its-panel" style={{ padding: '20px' }}>
          <div
            style={{
              fontSize: '12px',
              fontWeight: 700,
              letterSpacing: '0.05em',
              color: 'var(--its-text-muted)',
            }}
          >
            {(result.empty_reason || result.status).replace(/_/g, ' ')}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '8px', lineHeight: 1.7, maxWidth: '640px' }}>
            {result.detail ||
              'No polled signal state was recorded on this corridor during the selected window. ' +
                'The diagram is not drawn rather than drawn empty, because an empty diagram reads ' +
                'as "no green was displayed" when what actually happened is that nothing was observed.'}
          </div>
          {result.junction_count != null && (
            <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px' }}>
              {result.junctions_with_observations ?? 0} of {result.junction_count} junction(s) reported
              state in this window.
            </div>
          )}
        </div>
      )}

      {!loading && !error && result?.status === 'COMPUTED' && (
        <>
          <div className="its-panel">
            <div className="its-panel-header">
              <span>{result.corridor_name}</span>
              <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                {formatTimestamp(result.window_start)} - {formatTimestamp(result.window_end)}
              </span>
            </div>

            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '20px',
                padding: '11px 14px',
                borderBottom: '1px solid var(--its-border-subtle)',
                fontSize: '11px',
              }}
            >
              <span>
                <span className="its-metric-label">LENGTH </span>
                <span className="mono">{result.corridor_length_m?.toFixed(0)} m</span>
              </span>
              <span>
                <span className="its-metric-label">JUNCTIONS REPORTING </span>
                <span className="mono">
                  {result.junctions_with_observations}/{result.junction_count}
                </span>
              </span>
              <span>
                <span className="its-metric-label">MODE </span>
                <span className="mono">{result.coordination_mode || 'UNSET'}</span>
              </span>
              {result.configured_cycle_length_sec != null && (
                <span>
                  <span className="its-metric-label">CONFIGURED CYCLE </span>
                  <span className="mono">{result.configured_cycle_length_sec}s</span>
                  <span style={{ fontSize: '9px', color: 'var(--its-text-muted)' }}>
                    {' '}(configured, not measured)
                  </span>
                </span>
              )}
            </div>

            <StringlineDiagram result={result} />
          </div>

          {/* Progression between adjacent junctions */}
          <div className="its-panel" style={{ marginTop: '14px' }}>
            <div className="its-panel-header">
              <span>
                <GitCommitHorizontal size={13} style={{ verticalAlign: '-2px', marginRight: '5px' }} />
                MEASURED PROGRESSION
              </span>
              <span style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                {progression?.segments_computed ?? 0} of {progression?.segments_total ?? 0} segment(s)
              </span>
            </div>

            {!progression?.segments?.length ? (
              <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
                NO ADJACENT JUNCTION PAIRS TO COMPARE.
              </div>
            ) : (
              <div className="its-table-container">
                <table className="its-table">
                  <thead>
                    <tr>
                      <th>Segment</th>
                      <th style={{ width: '90px' }}>Distance</th>
                      <th style={{ width: '110px' }}>Median offset</th>
                      <th style={{ width: '120px' }}>Implied speed</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {progression.segments.map((segment: any, i: number) => (
                      <tr key={i}>
                        <td style={{ fontSize: '11px' }}>
                          {segment.from} <span style={{ color: 'var(--its-text-muted)' }}>to</span>{' '}
                          {segment.to}
                        </td>
                        <td className="mono">
                          {segment.distance_m != null ? `${segment.distance_m.toFixed(0)} m` : '--'}
                        </td>
                        <td className="mono">
                          {segment.median_offset_sec != null ? `${segment.median_offset_sec}s` : '--'}
                          {segment.measurement_resolution_sec != null && (
                            <span style={{ fontSize: '9px', color: 'var(--its-text-muted)' }}>
                              {' '}±{segment.measurement_resolution_sec}s
                            </span>
                          )}
                        </td>
                        <td
                          className="mono"
                          style={{
                            fontWeight: 700,
                            color:
                              segment.implied_progression_speed_kph != null
                                ? 'var(--its-text-primary)'
                                : 'var(--its-text-muted)',
                          }}
                        >
                          {segment.implied_progression_speed_kph != null
                            ? `${segment.implied_progression_speed_kph} km/h`
                            : '--'}
                        </td>
                        <td>
                          <div
                            style={{
                              fontSize: '9px',
                              fontWeight: 700,
                              letterSpacing: '0.04em',
                              color:
                                segment.status === 'COMPUTED'
                                  ? 'var(--its-status-normal)'
                                  : 'var(--its-text-muted)',
                            }}
                          >
                            {SEGMENT_STATUS_LABEL[segment.status] || segment.status.replace(/_/g, ' ')}
                          </div>
                          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '3px', lineHeight: 1.5 }}>
                            {segment.detail || segment.caveat}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {progression?.resolution_note && (
              <div
                style={{
                  padding: '10px 14px',
                  borderTop: '1px solid var(--its-border-subtle)',
                  fontSize: '10px',
                  color: 'var(--its-text-muted)',
                  lineHeight: 1.7,
                }}
              >
                {progression.resolution_note}
              </div>
            )}
          </div>

          {/* Method notes travel with the diagram, not in a help page. */}
          <div
            className="its-panel"
            style={{ marginTop: '14px', padding: '12px 14px', fontSize: '10px', color: 'var(--its-text-muted)', lineHeight: 1.7 }}
          >
            <div style={{ marginBottom: '6px' }}>
              <strong style={{ color: 'var(--its-text-secondary)' }}>DATA BASIS: </strong>
              {result.data_basis}
            </div>
            <div>
              <strong style={{ color: 'var(--its-text-secondary)' }}>DISTANCE BASIS: </strong>
              {result.distance_basis}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
