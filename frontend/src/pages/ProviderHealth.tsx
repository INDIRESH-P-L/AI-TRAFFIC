import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity, AlertTriangle, CircleSlash, Radio, RefreshCw, ShieldAlert, Wifi, Zap,
} from 'lucide-react';
import { api } from '../api/client';
import { SkeletonCard, SkeletonRows } from '../components/Skeleton';
import { useTickingAge } from '../hooks/useTickingAge';
import { formatAge, formatTimestamp } from '../lib/quality';
import { useConsole } from '../context/ConsoleContext';

/**
 * TRAFFICINTEL AI - Provider Health & Stream Diagnostics
 *
 * The page that answers "is the platform actually receiving anything?".
 *
 * `UNKNOWN` is rendered as its own state, visually distinct from healthy. A
 * provider nobody has probed has not been shown to work, and colouring it
 * green because nothing has failed yet is exactly the kind of reassurance a
 * control room should not be given.
 */

const STATE_STYLE: Record<string, { color: string; bg: string; border: string; label: string }> = {
  HEALTHY: {
    color: 'var(--its-signal-green)', bg: 'var(--its-signal-green-bg)',
    border: 'var(--its-signal-green-border)', label: 'HEALTHY',
  },
  DEGRADED: {
    color: 'var(--its-signal-yellow)', bg: 'var(--its-signal-yellow-bg)',
    border: 'var(--its-signal-yellow-border)', label: 'DEGRADED',
  },
  FAILED: {
    color: 'var(--its-signal-red)', bg: 'var(--its-signal-red-bg)',
    border: 'var(--its-signal-red-border)', label: 'FAILED',
  },
  UNKNOWN: {
    color: 'var(--its-text-muted)', bg: 'var(--its-stale-bg)',
    border: 'var(--its-border-default)', label: 'UNKNOWN',
  },
};

const ProviderCard: React.FC<{ provider: any }> = ({ provider }) => {
  const style = STATE_STYLE[provider.state] ?? STATE_STYLE.UNKNOWN;
  const lastCheckAge = useTickingAge(provider.last_checked_at);
  const circuit = provider.circuit ?? {};
  const neverProbed = provider.total_checks === 0;

  return (
    <div
      className="its-card"
      style={{ borderColor: style.border, background: style.bg }}
    >
      <div className="its-card-header">
        <span className="its-card-title">
          <Radio size={14} color={style.color} />
          <span>{provider.label}</span>
        </span>
        <span
          className="mono"
          style={{
            fontSize: 'var(--text-2xs)', fontWeight: 700, color: style.color,
            border: `1px solid ${style.border}`, borderRadius: 'var(--radius-full)',
            padding: '2px 8px',
          }}
        >
          {style.label}
        </span>
      </div>

      {neverProbed ? (
        <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.6 }}>
          This provider has never been contacted, so nothing is known about it.
          Unknown is not the same as working.
        </div>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '10px' }}>
            {[
              ['Error rate', provider.error_rate === null ? '—' : `${(provider.error_rate * 100).toFixed(1)}%`],
              ['Latency p95', provider.latency_p95_ms === null ? '—' : `${provider.latency_p95_ms} ms`],
              ['Checks', String(provider.total_checks)],
              ['Failures', String(provider.total_failures)],
            ].map(([label, value]) => (
              <div key={label}>
                <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                  {label}
                </div>
                <div className="mono" style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>
                  {value}
                </div>
              </div>
            ))}
          </div>

          <div
            className="mono"
            style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px' }}
            title={formatTimestamp(provider.last_checked_at)}
          >
            LAST CHECKED {formatAge(lastCheckAge)} AGO · {provider.measurement_basis}
          </div>

          {circuit.state && circuit.state !== 'CLOSED' && (
            <div
              style={{
                marginTop: '10px', padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--its-signal-red-border)',
                background: 'var(--its-signal-red-bg)', fontSize: 'var(--text-2xs)',
                display: 'flex', gap: '8px', alignItems: 'flex-start',
              }}
            >
              <CircleSlash size={13} color="var(--its-signal-red)" style={{ marginTop: 1 }} />
              <div>
                <strong>CIRCUIT {circuit.state}</strong> — calls are being refused for
                another {circuit.retry_after_sec}s rather than waiting for more timeouts.
                {circuit.last_error && (
                  <div className="mono" style={{ marginTop: '4px', color: 'var(--its-text-secondary)' }}>
                    {circuit.last_error}
                  </div>
                )}
              </div>
            </div>
          )}

          {provider.last_error && circuit.state === 'CLOSED' && (
            <div className="mono" style={{ fontSize: '10px', color: 'var(--its-signal-red)', marginTop: '8px' }}>
              LAST ERROR: {provider.last_error}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export const ProviderHealth: React.FC = () => {
  const [health, setHealth] = useState<any>(null);
  const [stream, setStream] = useState<any>(null);
  const [poller, setPoller] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { connection, lastEventAt } = useConsole();
  const lastEventAge = useTickingAge(lastEventAt);

  const load = useCallback(async (spinner = false) => {
    if (spinner) setLoading(true);
    setError(null);
    try {
      const [h, s, p] = await Promise.all([
        api.getProviderHealth(),
        api.getStreamHealth().catch(() => null),
        api.getPollerStatus().catch(() => null),
      ]);
      setHealth(h);
      setStream(s);
      setPoller(p);
    } catch (err: any) {
      setError(err.message || 'Could not load provider health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(true);
    const timer = setInterval(() => load(), 15000);
    return () => clearInterval(timer);
  }, [load]);

  const providers: any[] = health?.providers ?? [];
  const byState = health?.summary?.by_state ?? {};

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* Roll-up ---------------------------------------------------------- */}
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <Activity size={14} color="var(--its-text-accent)" />
            <span>Provider Health</span>
          </span>
          <button onClick={() => load(true)} className="its-btn" style={{ padding: '3px 8px' }}>
            <RefreshCw size={12} className={loading ? 'pulse-indicator' : ''} />
            <span>Refresh</span>
          </button>
        </div>

        {loading && !health ? (
          <SkeletonRows rows={1} label="Provider health summary" />
        ) : (
          <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap' }}>
            {Object.keys(STATE_STYLE).map(state => {
              const style = STATE_STYLE[state];
              const count = byState[state] ?? 0;
              return (
                <div key={state} style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                  <span
                    style={{
                      width: 10, height: 10, borderRadius: '50%',
                      background: style.color, border: `1px solid ${style.border}`,
                    }}
                  />
                  <span className="mono" style={{ fontWeight: 700 }}>{count}</span>
                  <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}>
                    {style.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {health?.note && (
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '10px', lineHeight: 1.6 }}>
            {health.note}
          </div>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="its-card"
          style={{ borderColor: 'var(--its-signal-red-border)', background: 'var(--its-signal-red-bg)' }}
        >
          <strong>PROVIDER HEALTH UNAVAILABLE</strong>
          <div style={{ fontSize: 'var(--text-2xs)', marginTop: '4px' }}>{error}</div>
        </div>
      )}

      {/* Providers -------------------------------------------------------- */}
      {loading && !health ? (
        <div className="grid-3">
          <SkeletonCard label="Provider" metrics={4} />
          <SkeletonCard label="Provider" metrics={4} />
        </div>
      ) : providers.length === 0 ? (
        <div className="its-card">
          <div
            className="mono"
            style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}
          >
            {health?.empty_reason ?? 'NO_PROVIDER_HAS_BEEN_CONTACTED_YET'}
          </div>
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '8px', lineHeight: 1.6 }}>
            Health is measured from calls the platform actually made. Nothing appears
            here until a controller, camera or weather provider has been contacted.
          </div>
        </div>
      ) : (
        <div className="grid-3">
          {providers.map(provider => (
            <ProviderCard key={provider.key} provider={provider} />
          ))}
        </div>
      )}

      {/* Stream diagnostics ----------------------------------------------- */}
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <Wifi size={14} color="var(--its-text-teal)" />
            <span>Event Stream</span>
          </span>
          <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
            {connection}
            {lastEventAt ? ` · LAST EVENT ${formatAge(lastEventAge)} AGO` : ' · NO EVENTS THIS SESSION'}
          </span>
        </div>

        {stream ? (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px,1fr))', gap: '14px' }}>
              {[
                ['Connected consoles', stream.gateway?.connections ?? 0],
                ['Events published', stream.bus?.sequence ?? 0],
                ['Subscribers', stream.bus?.subscribers ?? 0],
                ['Dropped events', stream.bus?.total_dropped_events ?? 0],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                    {label}
                  </div>
                  <div
                    className="mono"
                    style={{
                      fontSize: 'var(--text-md)', fontWeight: 700,
                      color: label === 'Dropped events' && Number(value) > 0
                        ? 'var(--its-signal-red)' : 'var(--its-text-primary)',
                    }}
                  >
                    {String(value)}
                  </div>
                </div>
              ))}
            </div>

            {Number(stream.bus?.total_dropped_events ?? 0) > 0 && (
              <div
                style={{
                  marginTop: '12px', padding: '10px 12px', borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--its-signal-yellow-border)',
                  background: 'var(--its-signal-yellow-bg)', fontSize: 'var(--text-2xs)',
                  display: 'flex', gap: '8px',
                }}
              >
                <AlertTriangle size={13} color="var(--its-signal-yellow)" />
                <span>{stream.note}</span>
              </div>
            )}

            {Object.keys(stream.bus?.published_by_topic ?? {}).length > 0 && (
              <div style={{ marginTop: '12px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--its-text-muted)', marginBottom: '6px' }}>
                  EVENTS BY TOPIC
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {Object.entries(stream.bus.published_by_topic).map(([topic, count]) => (
                    <span
                      key={topic}
                      className="mono"
                      style={{
                        fontSize: '10px', padding: '2px 7px', borderRadius: 'var(--radius-full)',
                        background: 'var(--its-bg-subsurface)',
                        border: '1px solid var(--its-border-subtle)',
                      }}
                    >
                      {topic} · {String(count)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <SkeletonRows rows={1} label="Stream diagnostics" />
        )}
      </div>

      {/* Controller polling ------------------------------------------------ */}
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <Zap size={14} color="var(--its-text-indigo)" />
            <span>Controller Polling</span>
          </span>
          <button
            onClick={async () => {
              await api.pollNow().catch(() => null);
              load();
            }}
            className="its-btn"
            style={{ padding: '3px 8px' }}
          >
            <RefreshCw size={12} />
            <span>Poll now</span>
          </button>
        </div>

        {poller ? (
          <>
            <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap', fontSize: 'var(--text-2xs)' }}>
              <span>
                Status:{' '}
                <span className="mono" style={{ fontWeight: 700, color: poller.running ? 'var(--its-signal-green)' : 'var(--its-text-muted)' }}>
                  {poller.running ? 'RUNNING' : 'STOPPED'}
                </span>
              </span>
              <span>Interval: <span className="mono">{poller.interval_sec}s</span></span>
              <span>Cycles: <span className="mono">{poller.cycles_completed}</span></span>
            </div>

            {poller.last_cycle ? (
              <div style={{ marginTop: '10px', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)' }}>
                Last cycle polled <strong>{poller.last_cycle.controllers_polled}</strong> controller(s)
                and skipped <strong>{poller.last_cycle.controllers_skipped}</strong> in{' '}
                {poller.last_cycle.duration_sec}s.
                {(poller.last_cycle.skipped ?? []).length > 0 && (
                  <ul style={{ margin: '6px 0 0', paddingLeft: '18px', lineHeight: 1.7 }}>
                    {poller.last_cycle.skipped.map((entry: any, i: number) => (
                      <li key={i}>
                        <span className="mono">{entry.name}</span> — {entry.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <div className="mono" style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginTop: '10px' }}>
                NO POLL CYCLE HAS RUN YET
              </div>
            )}

            <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px', lineHeight: 1.6 }}>
              {poller.note}
            </div>
          </>
        ) : (
          <SkeletonRows rows={1} label="Poller status" />
        )}
      </div>
    </div>
  );
};
