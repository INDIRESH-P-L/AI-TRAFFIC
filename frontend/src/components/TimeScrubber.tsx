import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { History, Pause, Play, RotateCcw, SkipBack, SkipForward } from 'lucide-react';
import { api } from '../api/client';
import { MeasuredValue } from './provenance/Provenance';
import { Skeleton } from './Skeleton';
import { formatTimestamp, normalizeQuality } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Historical replay scrubber
 *
 * Replays REAL stored telemetry for one junction. Three rules make this a
 * record rather than an animation:
 *
 * 1. The track only contains samples that exist. Nothing is interpolated
 *    between them, so a sensor outage shows as a gap in the track, not a line
 *    drawn through it.
 * 2. Playback steps sample-to-sample, not on a wall clock, so two samples an
 *    hour apart do not imply anything happened in between.
 * 3. A window with too few samples refuses to render a trend and says so.
 */

interface Props {
  junctionId: string | null;
  junctionName?: string;
}

const WINDOW_OPTIONS = [
  { label: '15m', minutes: 15 },
  { label: '1h', minutes: 60 },
  { label: '6h', minutes: 360 },
  { label: '24h', minutes: 1440 },
  { label: '7d', minutes: 10080 },
];

const PLAYBACK_INTERVAL_MS = 900;

export const TimeScrubber: React.FC<Props> = ({ junctionId, junctionName }) => {
  const [minutes, setMinutes] = useState(60);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const playTimer = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!junctionId) return;
    setLoading(true);
    setError(null);
    setPlaying(false);
    try {
      const response = await api.getJunctionReplay(junctionId, minutes);
      setData(response);
      setIndex(0);
    } catch (err: any) {
      setError(err.message || 'Could not load stored telemetry');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [junctionId, minutes]);

  useEffect(() => {
    load();
  }, [load]);

  const samples: any[] = useMemo(() => data?.metrics ?? [], [data]);
  const sufficient = data?.sufficient_data === true && samples.length > 0;

  useEffect(() => {
    if (!playing || !sufficient) return;

    playTimer.current = window.setInterval(() => {
      setIndex(prev => {
        if (prev >= samples.length - 1) {
          setPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, PLAYBACK_INTERVAL_MS);

    return () => {
      if (playTimer.current !== null) window.clearInterval(playTimer.current);
    };
  }, [playing, sufficient, samples.length]);

  const current = samples[index];

  // Signal events that fall at or before the scrubbed moment.
  const signalEventsSoFar = useMemo(() => {
    if (!current || !data?.signal_events) return [];
    const cursor = new Date(current.timestamp).getTime();
    return data.signal_events.filter((e: any) => new Date(e.timestamp).getTime() <= cursor);
  }, [current, data]);

  // Gap detection: a jump much larger than the median spacing is an outage,
  // and the scrubber labels it rather than gliding across it.
  const gapBefore = useMemo(() => {
    if (index === 0 || samples.length < 3) return null;
    const deltas: number[] = [];
    for (let i = 1; i < samples.length; i++) {
      deltas.push(
        new Date(samples[i].timestamp).getTime() - new Date(samples[i - 1].timestamp).getTime(),
      );
    }
    const sorted = [...deltas].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)] || 0;
    const thisDelta = deltas[index - 1];
    if (median > 0 && thisDelta > median * 4) return Math.round(thisDelta / 1000);
    return null;
  }, [index, samples]);

  if (!junctionId) {
    return (
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <History size={14} color="var(--its-text-accent)" />
            <span>Historical Replay</span>
          </span>
        </div>
        <div style={emptyText}>SELECT A JUNCTION TO REPLAY ITS STORED TELEMETRY</div>
      </div>
    );
  }

  return (
    <div className="its-card">
      <div className="its-card-header">
        <span className="its-card-title">
          <History size={14} color="var(--its-text-accent)" />
          <span>Historical Replay{junctionName ? ` — ${junctionName}` : ''}</span>
        </span>

        <div style={{ display: 'flex', gap: '4px' }}>
          {WINDOW_OPTIONS.map(option => (
            <button
              key={option.label}
              onClick={() => setMinutes(option.minutes)}
              className="its-btn"
              aria-pressed={minutes === option.minutes}
              style={{
                padding: '2px 7px', fontSize: '10px',
                borderColor: minutes === option.minutes ? 'var(--its-border-focused)' : undefined,
                color: minutes === option.minutes ? 'var(--its-text-accent)' : undefined,
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div aria-busy="true">
          <Skeleton height={16} style={{ marginBottom: 10 }} />
          <Skeleton height={44} />
        </div>
      )}

      {!loading && error && (
        <div role="alert" style={errorBlock}>
          <strong>REPLAY UNAVAILABLE</strong>
          <div style={{ marginTop: '4px' }}>{error}</div>
        </div>
      )}

      {!loading && !error && !sufficient && (
        <div style={{ padding: '18px 4px' }}>
          <div style={emptyText}>
            {data?.empty_reason === 'NO_STORED_TELEMETRY_FOR_THIS_WINDOW'
              ? 'NO STORED TELEMETRY FOR THIS WINDOW'
              : 'INSUFFICIENT DATA FOR REPLAY'}
          </div>
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '8px', lineHeight: 1.6 }}>
            {data
              ? `${data.sample_count} stored sample${data.sample_count === 1 ? '' : 's'} in the last ${minutes} minutes; ${data.minimum_samples_required} are required before a replay is drawn. Nothing is interpolated to fill the gap.`
              : 'No stored telemetry was returned for this junction.'}
          </div>
        </div>
      )}

      {!loading && !error && sufficient && current && (
        <>
          {/* Transport controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
            <button
              onClick={() => setIndex(0)}
              className="its-btn"
              style={transportBtn}
              aria-label="Jump to start of window"
            >
              <SkipBack size={13} />
            </button>
            <button
              onClick={() => setPlaying(p => !p)}
              className="its-btn its-btn-primary"
              style={transportBtn}
              aria-label={playing ? 'Pause replay' : 'Play replay'}
            >
              {playing ? <Pause size={13} /> : <Play size={13} />}
            </button>
            <button
              onClick={() => setIndex(samples.length - 1)}
              className="its-btn"
              style={transportBtn}
              aria-label="Jump to end of window"
            >
              <SkipForward size={13} />
            </button>
            <button onClick={load} className="its-btn" style={transportBtn} aria-label="Reload window">
              <RotateCcw size={13} />
            </button>

            <input
              type="range"
              min={0}
              max={samples.length - 1}
              value={index}
              onChange={e => {
                setPlaying(false);
                setIndex(Number(e.target.value));
              }}
              aria-label="Scrub through stored samples"
              aria-valuetext={`Sample ${index + 1} of ${samples.length}, recorded ${formatTimestamp(current.timestamp)}`}
              style={{ flex: 1, accentColor: 'var(--its-text-accent)' }}
            />

            <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', whiteSpace: 'nowrap' }}>
              {index + 1}/{samples.length}
            </span>
          </div>

          {/* Scrub position */}
          <div
            style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '6px 10px', borderRadius: 'var(--radius-sm)',
              background: 'var(--its-bg-subsurface)', marginBottom: '10px', flexWrap: 'wrap', gap: '6px',
            }}
          >
            <span className="mono" style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-primary)', fontWeight: 700 }}>
              {formatTimestamp(current.timestamp)}
            </span>
            <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              RECORDED SAMPLE · {String(current.data_quality)}
            </span>
          </div>

          {gapBefore !== null && (
            <div
              style={{
                padding: '6px 10px', borderRadius: 'var(--radius-sm)',
                border: '1px dashed var(--its-signal-yellow-border)',
                background: 'var(--its-signal-yellow-bg)',
                fontSize: 'var(--text-2xs)', color: 'var(--its-text-primary)', marginBottom: '10px',
              }}
            >
              GAP: no samples were stored for {gapBefore}s before this point. The track jumps
              rather than interpolating across the outage.
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '14px' }}>
            {[
              { label: 'Vehicles', value: current.vehicle_count, unit: undefined },
              { label: 'Speed', value: current.avg_speed_kph, unit: 'km/h' },
              { label: 'Occupancy', value: current.occupancy_pct, unit: '%' },
              { label: 'Queue', value: current.queue_length_meters, unit: 'm' },
              { label: 'Flow rate', value: current.flow_rate_vph, unit: 'veh/h' },
            ].map(metric => (
              <MeasuredValue
                key={metric.label}
                label={metric.label}
                value={metric.value}
                unit={metric.unit}
                emptyText="NOT MEASURED"
                provenance={{
                  state: normalizeQuality(current.data_quality),
                  age_sec: null,
                  observed_at: current.timestamp,
                  source: current.provenance?.sources_used ?? null,
                }}
              />
            ))}
          </div>

          {signalEventsSoFar.length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--its-text-muted)', marginBottom: '5px' }}>
                SIGNAL COMMANDS UP TO THIS POINT ({signalEventsSoFar.length})
              </div>
              {signalEventsSoFar.slice(-3).map((event: any, i: number) => (
                <div
                  key={i}
                  className="mono"
                  style={{ fontSize: '10px', color: 'var(--its-text-secondary)', padding: '2px 0' }}
                >
                  {formatTimestamp(event.timestamp)} · Ø{event.requested_phase} · {event.status}
                  {event.safety_passed === false && ' · SAFETY REJECTED'}
                </div>
              ))}
            </div>
          )}

          <div className="mono" style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '12px' }}>
            INTERPOLATION: {data.interpolation} · WINDOW {formatTimestamp(data.window_start)} → {formatTimestamp(data.window_end)}
          </div>
        </>
      )}
    </div>
  );
};

const emptyText: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 'var(--text-xs)',
  fontWeight: 700,
  color: 'var(--its-text-muted)',
  letterSpacing: '0.04em',
};

const errorBlock: React.CSSProperties = {
  padding: '10px 12px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--its-signal-red-border)',
  background: 'var(--its-signal-red-bg)',
  fontSize: 'var(--text-2xs)',
};

const transportBtn: React.CSSProperties = {
  padding: '4px 8px',
  height: '28px',
};
