import React from 'react';
import { AlertOctagon, Radar, ShieldQuestion } from 'lucide-react';

/**
 * TRAFFICINTEL AI - Fusion Incident Detection Panel
 *
 * Renders GET /intelligence/incident-fusion/{id}. Every segment names the
 * sources that corroborated a symptom and, separately, the sources that were
 * evaluated and did not - an operator deciding whether to dispatch needs to
 * know that one of three detectors disagreed.
 *
 * The record action is labelled with exactly what it does: it files the
 * incident as DETECTED. The detector never verifies; a person does.
 */

export interface FusionResult {
  status: string;
  detail: string;
  segments: any[];
  probable_incidents: any[];
  unattributed_sources: any[];
  thresholds?: any;
  independence_basis?: string;
}

export interface RecordOutcome {
  recorded: any[];
  skipped: any[];
  note?: string;
}

const SEGMENT_COLORS: Record<string, string> = {
  PROBABLE_INCIDENT: 'var(--its-signal-red)',
  UNCORROBORATED_SINGLE_SOURCE: 'var(--its-signal-yellow)',
  PARTIAL_SYMPTOMS: 'var(--its-signal-yellow)',
  NO_INCIDENT_INDICATED: 'var(--its-signal-green)',
};

const channelText = (channel: any, flag: boolean | null, kind: 'occupancy' | 'speed'): string => {
  if (!channel || channel.status === 'NOT_MEASURED') return 'not reported by this source';
  if (channel.status === 'INSUFFICIENT_DATA') {
    return `insufficient samples (${channel.before_samples}/${channel.after_samples})`;
  }
  const unit = kind === 'occupancy' ? '%' : ' km/h';
  const change = `${channel.before_mean}${unit} → ${channel.after_mean}${unit}`;
  const verdict = flag ? (kind === 'occupancy' ? 'SPIKE' : 'DROP') : 'no symptom';
  return `${change} · ${verdict}`;
};

const SegmentCard: React.FC<{ segment: any }> = ({ segment }) => {
  const color = SEGMENT_COLORS[segment.status] || 'var(--its-text-muted)';

  return (
    <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '12px', fontWeight: 700, flex: 1 }}>{segment.approach}</span>
        <span style={{ fontSize: '10px', fontWeight: 700, color, letterSpacing: '0.04em' }}>
          {segment.status.replace(/_/g, ' ')}
        </span>
      </div>
      {segment.reason && (
        <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
          {segment.reason}
        </div>
      )}
      <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '5px', lineHeight: 1.6 }}>
        {segment.explanation}
      </div>
      <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '5px' }}>
        {segment.sources_reporting} source(s) reporting · {segment.configured_sensors} configured
      </div>

      {segment.corroborating_sources?.length > 0 && (
        <div style={{ fontSize: '10px', marginTop: '6px' }}>
          <strong>Corroborating: </strong>
          <span className="mono">{segment.corroborating_sources.join(', ')}</span>
        </div>
      )}
      {segment.evaluated_but_not_corroborating?.length > 0 && (
        <div style={{ fontSize: '10px', marginTop: '3px', color: 'var(--its-text-muted)' }}>
          <strong>Evaluated, no symptom: </strong>
          <span className="mono">{segment.evaluated_but_not_corroborating.join(', ')}</span>
        </div>
      )}

      {segment.source_assessments?.length > 0 && (
        <div className="its-table-container" style={{ marginTop: '8px' }}>
          <table className="its-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Occupancy</th>
                <th>Speed</th>
              </tr>
            </thead>
            <tbody>
              {segment.source_assessments.map((a: any) => (
                <tr key={a.source}>
                  <td className="mono" style={{ fontSize: '10px' }}>
                    {a.source}
                    <div style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>{a.sensor_kind}</div>
                  </td>
                  <td className="mono" style={{ fontSize: '10px' }}>
                    {channelText(a.occupancy, a.occupancy_spike, 'occupancy')}
                  </td>
                  <td className="mono" style={{ fontSize: '10px' }}>
                    {channelText(a.speed, a.speed_drop, 'speed')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {segment.corroboration_ratio !== null && segment.corroboration_ratio !== undefined && (
        <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.6 }}>
          Corroboration ratio <span className="mono">{segment.corroboration_ratio}</span> — {segment.corroboration_ratio_basis}
        </div>
      )}
    </div>
  );
};

export const FusionPanel: React.FC<{
  result: FusionResult;
  onRecord?: () => void;
  recording?: boolean;
  recordOutcome?: RecordOutcome | null;
  recordError?: string | null;
}> = ({ result, onRecord, recording, recordOutcome, recordError }) => {
  const probable = result.status === 'PROBABLE_INCIDENT';
  const evaluated = probable || result.status === 'NO_CORROBORATED_INCIDENT';
  const color = probable
    ? 'var(--its-signal-red)'
    : evaluated ? 'var(--its-signal-green)' : 'var(--its-text-muted)';
  const Icon = probable ? AlertOctagon : evaluated ? Radar : ShieldQuestion;

  return (
    <div className="its-panel">
      <div style={{ display: 'flex', gap: '10px', padding: '14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
        <Icon size={20} style={{ color, flexShrink: 0, marginTop: '2px' }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '13px', fontWeight: 800, color, letterSpacing: '0.04em' }}>
            {result.status.replace(/_/g, ' ')}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
            {result.detail}
          </div>
        </div>
      </div>

      {probable && onRecord && (
        <div
          style={{
            padding: '10px 14px',
            borderBottom: '1px solid var(--its-border-subtle)',
            background: 'var(--its-bg-elevated)',
          }}
        >
          <button className="its-btn its-btn-primary its-btn-sm" onClick={onRecord} disabled={recording}>
            {recording ? 'Recording…' : 'Record as DETECTED'}
          </button>
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.6 }}>
            Files each probable incident in the lifecycle's entry state with the corroborating
            observations attached as evidence. It does not verify anything; an operator does.
          </div>
          {recordError && (
            <div style={{ fontSize: '10px', color: 'var(--its-signal-red)', marginTop: '6px' }}>{recordError}</div>
          )}
          {recordOutcome && (
            <div style={{ fontSize: '10px', marginTop: '6px', lineHeight: 1.6 }}>
              {recordOutcome.recorded.map((r) => (
                <div key={r.incident_id}>
                  Recorded {r.approach} as <strong>{r.status}</strong> · {r.evidence_ids.length} evidence record(s)
                </div>
              ))}
              {recordOutcome.skipped.map((s) => (
                <div key={s.incident_id} style={{ color: 'var(--its-text-muted)' }}>
                  Skipped {s.approach}: {s.reason.replace(/_/g, ' ').toLowerCase()}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {result.unattributed_sources?.length > 0 && (
        <div
          style={{
            padding: '9px 14px',
            borderBottom: '1px solid var(--its-border-subtle)',
            fontSize: '10px',
            lineHeight: 1.6,
          }}
        >
          <strong>UNATTRIBUTED SOURCES: </strong>
          {result.unattributed_sources
            .map((u) => `${u.source} (${u.reason}, ${u.observations} obs)`)
            .join('; ')}
          . These could not be placed on a segment and were not guessed onto one.
        </div>
      )}

      {result.segments.length === 0 ? (
        <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
          NO SEGMENTS CONFIGURED. Approaches and lanes define where sensors sit; without them no
          observation can be corroborated.
        </div>
      ) : (
        result.segments.map((segment) => <SegmentCard key={segment.approach_id} segment={segment} />)
      )}

      {result.thresholds && (
        <div style={{ padding: '10px 14px', fontSize: '9px', color: 'var(--its-text-muted)', lineHeight: 1.6 }}>
          Thresholds: ≥{result.thresholds.min_independent_sources} independent sources · occupancy +
          {result.thresholds.min_occupancy_rise_pct_points} pct-points · speed −
          {Math.round(result.thresholds.min_speed_drop_fraction * 100)}% · 95% Welch interval
          excluding zero. {result.independence_basis}
        </div>
      )}
    </div>
  );
};
