import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity, ArrowUpRight, Camera as CameraIcon, Clock,
  ExternalLink, Radio, RefreshCw, ShieldCheck, Signal, X,
} from 'lucide-react';
import { api } from '../api/client';
import { MeasuredValue, ProvenanceChip, QualityDot } from './provenance/Provenance';
import { Skeleton, SkeletonRows } from './Skeleton';
import { useTickingAge } from '../hooks/useTickingAge';
import { formatAge, formatTimestamp, normalizeQuality } from '../lib/quality';
import type { QualityThresholds } from '../lib/quality';
import { useConsole } from '../context/ConsoleContext';
import { TrustBadge, trustAppearance, trustScoreText } from './TrustPanel';
import type { TrustResult } from './TrustPanel';

/**
 * TRAFFICINTEL AI - Junction side drawer
 *
 * The click-through from a map marker: live phase state, detector health and a
 * recent-events timeline for one junction, each with its own provenance.
 *
 * The phase display deliberately shows the phases the CONTROLLER reported as
 * green, plus any in clearance. When the controller's state is unreadable it
 * shows "SIGNAL STATE: UNAVAILABLE" rather than the last phase it happened to
 * report, because a frozen phase readout is how an operator ends up acting on
 * a junction that stopped talking ten minutes ago.
 */

interface Props {
  junctionId: string | null;
  mapFeature?: any;
  thresholds?: QualityThresholds;
  onClose: () => void;
  onIssueCommand?: (controllerId: string | null) => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'var(--its-signal-red)',
  WARNING: 'var(--its-signal-yellow)',
  INFO: 'var(--its-text-accent)',
};

const PhaseChip: React.FC<{ phase: number; kind: 'GREEN' | 'CLEARING' }> = ({ phase, kind }) => (
  <span
    className="mono"
    style={{
      display: 'inline-flex', alignItems: 'center', gap: '5px',
      padding: '3px 9px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
      fontSize: 'var(--text-xs)',
      background: kind === 'GREEN' ? 'var(--its-signal-green-bg)' : 'var(--its-signal-yellow-bg)',
      border: `1px solid ${kind === 'GREEN' ? 'var(--its-signal-green-border)' : 'var(--its-signal-yellow-border)'}`,
      color: kind === 'GREEN' ? 'var(--its-signal-green)' : 'var(--its-signal-yellow)',
    }}
  >
    <span
      style={{
        width: 8, height: 8, borderRadius: '50%',
        background: kind === 'GREEN' ? 'var(--its-signal-green)' : 'var(--its-signal-yellow)',
      }}
    />
    Ø{phase}
  </span>
);

const TimelineRow: React.FC<{ event: any }> = ({ event }) => {
  const age = useTickingAge(event.timestamp);
  return (
    <div
      style={{
        display: 'flex', gap: '10px', padding: '8px 10px',
        borderLeft: `2px solid ${SEVERITY_COLOR[event.severity] ?? 'var(--its-border-default)'}`,
        background: 'var(--its-bg-subsurface)',
        borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexWrap: 'wrap' }}>
          <span
            className="mono"
            style={{
              fontSize: '9px', fontWeight: 700, padding: '1px 5px',
              borderRadius: 'var(--radius-xs)', background: 'var(--its-bg-elevated)',
              border: '1px solid var(--its-border-subtle)', color: 'var(--its-text-muted)',
            }}
          >
            {event.kind}
          </span>
          {event.safety_passed === false && (
            <span
              className="mono"
              style={{ fontSize: '9px', color: 'var(--its-signal-red)', fontWeight: 700 }}
            >
              SAFETY REJECTED
            </span>
          )}
        </div>

        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--its-text-primary)', marginTop: '3px' }}>
          {event.title}
        </div>

        {event.detail && (
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '2px', lineHeight: 1.5 }}>
            {event.detail}
          </div>
        )}

        <div
          className="mono"
          style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '4px' }}
          title={formatTimestamp(event.timestamp)}
        >
          {formatAge(age)} ago · {event.source}
        </div>
      </div>
    </div>
  );
};

export const JunctionDrawer: React.FC<Props> = ({
  junctionId,
  mapFeature,
  thresholds,
  onClose,
  onIssueCommand,
}) => {
  const [timeline, setTimeline] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [traffic, setTraffic] = useState<any>(null);
  const [trust, setTrust] = useState<TrustResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { subscribe } = useConsole();

  const load = useCallback(async () => {
    if (!junctionId) return;
    setLoading(true);
    setError(null);
    try {
      const [timelineRes, detailRes, trafficRes, trustRes] = await Promise.all([
        api.getJunctionTimeline(junctionId, 24, 40),
        api.getIntersection(junctionId).catch(() => null),
        api.getIntersectionTraffic(junctionId).catch(() => null),
        // The trust score is the frame for everything else in this drawer, so
        // its absence must not blank the drawer: a failed assessment leaves the
        // banner out rather than hiding the junction's actual state.
        api.getJunctionTrust(junctionId).catch(() => null),
      ]);
      setTimeline(timelineRes);
      setDetail(detailRes);
      setTraffic(trafficRes);
      setTrust(trustRes);
    } catch (err: any) {
      setError(err.message || 'Could not load junction detail');
    } finally {
      setLoading(false);
    }
  }, [junctionId]);

  useEffect(() => {
    load();
  }, [load]);

  // Live refresh: any event touching signals or incidents re-reads this junction.
  useEffect(() => {
    if (!junctionId) return;
    const unsubSignal = subscribe('signal.*', () => load());
    const unsubIncident = subscribe('incident.*', () => load());
    return () => {
      unsubSignal();
      unsubIncident();
    };
  }, [junctionId, subscribe, load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!junctionId) return null;

  const controller = mapFeature?.controller;
  const stateReadable =
    controller && controller.connection_status === 'CONNECTED' && controller.active_phase !== undefined;
  const greenPhases: number[] =
    mapFeature?.controller?.active_phase != null ? [mapFeature.controller.active_phase] : [];
  const clearingPhases: number[] = controller?.clearing_phases ?? [];

  const name = mapFeature?.name || detail?.name || 'Junction';
  const code = mapFeature?.code || detail?.code;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="junction-drawer" role="dialog" aria-modal="true" aria-label={`Junction ${name}`}>
        <div className="drawer-header">
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontSize: 'var(--text-sm)', fontWeight: 700,
                color: 'var(--its-text-primary)', overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
            >
              {name}
            </div>
            <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              {code ?? junctionId.slice(0, 8)}
            </div>
          </div>

          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <button onClick={load} className="its-btn" style={{ padding: '4px 8px' }} title="Re-read junction">
              <RefreshCw size={12} className={loading ? 'pulse-indicator' : ''} />
            </button>
            <button
              onClick={onClose}
              aria-label="Close junction drawer"
              style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--its-text-muted)' }}
            >
              <X size={17} />
            </button>
          </div>
        </div>

        <div className="junction-drawer-body">
          {error && (
            <div
              role="alert"
              style={{
                padding: '10px 12px', borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--its-signal-red-border)',
                background: 'var(--its-signal-red-bg)', fontSize: 'var(--text-2xs)',
              }}
            >
              <strong>COULD NOT LOAD JUNCTION</strong>
              <div style={{ marginTop: '4px' }}>{error}</div>
            </div>
          )}

          {/* --- Data trust ---------------------------------------------
              Placed above everything else on purpose: how much to believe
              the panels below is the first thing an operator needs, not a
              footnote under them. */}
          {trust && (
            <section
              className="its-card"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '10px 12px',
                borderLeft: `3px solid ${trustAppearance(trust.band).border}`,
              }}
            >
              <TrustBadge band={trust.band} score={trust.score} size="md" />
              <div style={{ flex: 1, minWidth: 0, fontSize: 'var(--text-2xs)', lineHeight: 1.5 }}>
                <div style={{ color: 'var(--its-text-muted)' }}>
                  {trust.band === 'UNRATED'
                    ? 'Not enough is measured here to rate. This is not a bad score - it is no score.'
                    : trust.weakest_component
                      ? `Limiting factor: ${trust.weakest_component.explanation}`
                      : trustAppearance(trust.band).meaning}
                </div>
                {trust.ai_gate && !trust.ai_gate.allowed && (
                  <div style={{ color: 'var(--its-status-warning)', marginTop: '3px' }}>
                    AI recommendations withheld at this junction (score {trustScoreText(trust)} /
                    threshold {trust.ai_gate.threshold}).
                  </div>
                )}
              </div>
              <Link
                to="/data-trust"
                className="its-btn its-btn-sm"
                style={{ flexShrink: 0 }}
                title="Full component breakdown"
              >
                Breakdown
              </Link>
            </section>
          )}

          {/* --- Signal state ------------------------------------------- */}
          <section className="its-card">
            <div className="its-card-header">
              <span className="its-card-title">
                <Signal size={14} color="var(--its-text-accent)" />
                <span>Signal State</span>
              </span>
              {controller && <ProvenanceChip provenance={controller.quality} thresholds={thresholds} compact />}
            </div>

            {!controller || controller.connection_status === 'NOT_CONFIGURED' ? (
              <div style={emptyText}>SIGNAL CONTROLLER: NOT CONNECTED</div>
            ) : !stateReadable ? (
              <>
                <div style={emptyText}>SIGNAL STATE: UNAVAILABLE</div>
                <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '6px', lineHeight: 1.6 }}>
                  The controller is <strong>{controller.connection_status}</strong>. Its phase
                  state cannot be read, so no phase is shown — the last known phase is
                  deliberately not displayed as if it were live.
                </div>
              </>
            ) : (
              <>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '10px' }}>
                  {greenPhases.length > 0 ? (
                    greenPhases.map(p => <PhaseChip key={p} phase={p} kind="GREEN" />)
                  ) : (
                    <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>
                      No phase displaying green (clearance interval)
                    </span>
                  )}
                  {clearingPhases.map(p => <PhaseChip key={`c${p}`} phase={p} kind="CLEARING" />)}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: 'var(--text-2xs)' }}>
                  <div>
                    <span style={{ color: 'var(--its-text-muted)' }}>Protocol</span>
                    <div className="mono">{controller.protocol ?? '—'}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--its-text-muted)' }}>Connection</span>
                    <div className="mono">{controller.connection_status}</div>
                  </div>
                </div>
              </>
            )}

            {onIssueCommand && (
              <button
                onClick={() => onIssueCommand(controller?.id ?? null)}
                className="its-btn its-btn-primary"
                style={{ width: '100%', justifyContent: 'center', marginTop: '12px' }}
                disabled={!controller?.id}
                title={controller?.id ? 'Open the guided command workflow' : 'No controller configured'}
              >
                <ShieldCheck size={13} />
                <span>Issue signal command</span>
              </button>
            )}
          </section>

          {/* --- Traffic telemetry --------------------------------------- */}
          <section className="its-card">
            <div className="its-card-header">
              <span className="its-card-title">
                <Activity size={14} color="var(--its-text-teal)" />
                <span>Measured Traffic</span>
              </span>
            </div>

            {loading && !traffic ? (
              <Skeleton height={52} />
            ) : !traffic || traffic.data_quality === 'NO_DATA' ? (
              <>
                <div style={emptyText}>NO SENSOR DATA AVAILABLE</div>
                <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '6px', lineHeight: 1.6 }}>
                  {traffic?.provenance?.status ?? 'No telemetry source has reported for this junction.'}
                </div>
              </>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '14px' }}>
                {[
                  { label: 'Vehicles', value: traffic.vehicle_count, unit: null },
                  { label: 'Speed', value: traffic.avg_speed_kph, unit: 'km/h' },
                  { label: 'Occupancy', value: traffic.occupancy_pct, unit: '%' },
                  { label: 'Flow rate', value: traffic.flow_rate_vph, unit: 'veh/h' },
                ].map(metric => (
                  <MeasuredValue
                    key={metric.label}
                    label={metric.label}
                    value={metric.value}
                    unit={metric.unit ?? undefined}
                    thresholds={thresholds}
                    emptyText="NOT MEASURED"
                    provenance={{
                      state: normalizeQuality(traffic.data_quality),
                      age_sec: null,
                      observed_at: traffic.timestamp ?? null,
                      source: traffic.provenance?.sources_used ?? null,
                    }}
                  />
                ))}
              </div>
            )}

            {traffic?.calculation_method && (
              <div className="mono" style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '10px' }}>
                METHOD: {traffic.calculation_method}
                {traffic.sample_window_sec
                  ? ` · WINDOW ${traffic.sample_window_sec}s`
                  : ' · SAMPLE WINDOW NOT RECORDED'}
              </div>
            )}
          </section>

          {/* --- Detector status ----------------------------------------- */}
          <section className="its-card">
            <div className="its-card-header">
              <span className="its-card-title">
                <Radio size={14} color="var(--its-text-indigo)" />
                <span>Detectors & Cameras</span>
              </span>
            </div>

            {loading && !detail ? (
              <SkeletonRows rows={2} label="Detector status" />
            ) : (
              <>
                {(detail?.sensors ?? []).length === 0 && (detail?.cameras ?? []).length === 0 ? (
                  <div style={emptyText}>NO DETECTORS OR CAMERAS CONFIGURED</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {(detail?.sensors ?? []).map((sensor: any) => (
                      <div key={sensor.id} style={deviceRow}>
                        <QualityDot state={normalizeQuality(sensor.quality)} />
                        <span style={{ flex: 1, minWidth: 0, fontSize: 'var(--text-2xs)' }}>
                          {sensor.name}
                          <span style={{ color: 'var(--its-text-muted)' }}> · {sensor.sensor_type}</span>
                        </span>
                        <ProvenanceChip
                          provenance={{
                            state: normalizeQuality(sensor.quality),
                            age_sec: null,
                            observed_at: sensor.last_observation_timestamp ?? null,
                            source: `sensor:${sensor.sensor_type}`,
                          }}
                          thresholds={thresholds}
                          compact
                        />
                      </div>
                    ))}

                    {(detail?.cameras ?? []).map((camera: any) => (
                      <div key={camera.id} style={deviceRow}>
                        <CameraIcon size={12} color="var(--its-text-muted)" />
                        <span style={{ flex: 1, minWidth: 0, fontSize: 'var(--text-2xs)' }}>
                          {camera.name}
                          <span style={{ color: 'var(--its-text-muted)' }}> · {camera.stream_status}</span>
                        </span>
                        <ProvenanceChip
                          provenance={{
                            state: camera.stream_status === 'CONNECTED' ? 'FRESH' : 'NO_DATA',
                            age_sec: null,
                            observed_at: camera.last_frame_timestamp ?? null,
                            source: `camera:${camera.name}`,
                          }}
                          thresholds={thresholds}
                          compact
                        />
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>

          {/* --- Timeline ------------------------------------------------- */}
          <section className="its-card">
            <div className="its-card-header">
              <span className="its-card-title">
                <Clock size={14} color="var(--its-text-brand)" />
                <span>Recent Events</span>
              </span>
              {timeline && (
                <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                  {timeline.total_in_window} IN {timeline.window_hours}H
                </span>
              )}
            </div>

            {loading && !timeline ? (
              <SkeletonRows rows={4} label="Junction timeline" />
            ) : !timeline || timeline.events.length === 0 ? (
              <div style={emptyText}>
                {timeline?.empty_reason === 'NO_RECORDED_EVENTS_IN_WINDOW'
                  ? 'NO RECORDED EVENTS IN THIS WINDOW'
                  : 'NO EVENT HISTORY'}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {timeline.events.map((event: any, i: number) => (
                  <TimelineRow key={`${event.resource_id}-${i}`} event={event} />
                ))}
              </div>
            )}
          </section>

          <Link
            to={`/intersections/${junctionId}`}
            className="its-btn"
            style={{ justifyContent: 'center', textDecoration: 'none' }}
          >
            <ExternalLink size={13} />
            <span>Open full junction page</span>
            <ArrowUpRight size={12} />
          </Link>
        </div>
      </aside>
    </>
  );
};

const emptyText: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 'var(--text-xs)',
  fontWeight: 700,
  color: 'var(--its-text-muted)',
  letterSpacing: '0.04em',
};

const deviceRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  padding: '6px 8px',
  borderRadius: 'var(--radius-xs)',
  background: 'var(--its-bg-subsurface)',
};
