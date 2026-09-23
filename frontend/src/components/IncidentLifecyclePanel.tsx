import React, { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2, Clock, FileText, Paperclip, Timer, UserCheck,
} from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { useTickingAge } from '../hooks/useTickingAge';
import { formatAge, formatTimestamp } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Incident Lifecycle Panel
 *
 * SLA clocks, the append-only timeline, and traceable evidence for one
 * incident.
 *
 * The SLA clocks tick live and go red the moment a target is missed, rather
 * than on the next page load. An SLA that only shows a breach after a refresh
 * is a stopwatch you have to remember to look at.
 */

const SLA_STYLE: Record<string, { color: string; label: string }> = {
  MET: { color: 'var(--its-signal-green)', label: 'MET' },
  RUNNING: { color: 'var(--its-text-accent)', label: 'RUNNING' },
  BREACHED: { color: 'var(--its-signal-red)', label: 'BREACHED' },
  NO_TARGET_SET: { color: 'var(--its-text-muted)', label: 'NO TARGET' },
};

const SlaClock: React.FC<{
  title: string;
  clock: any;
  detectedAt: string | null;
}> = ({ title, clock, detectedAt }) => {
  // Anchored to detection so the clock keeps moving without a refresh.
  const elapsed = useTickingAge(clock?.status === 'RUNNING' ? detectedAt : null);
  const target = clock?.target_sec;

  const liveElapsed = clock?.status === 'RUNNING' && elapsed !== null
    ? elapsed
    : clock?.elapsed_sec ?? null;

  const liveStatus =
    clock?.status === 'RUNNING' && target && liveElapsed !== null && liveElapsed > target
      ? 'BREACHED'
      : clock?.status;

  const style = SLA_STYLE[liveStatus] ?? SLA_STYLE.NO_TARGET_SET;
  const remaining = target !== null && target !== undefined && liveElapsed !== null
    ? target - liveElapsed
    : null;

  return (
    <div
      style={{
        flex: 1, minWidth: '160px', padding: '10px 12px',
        borderRadius: 'var(--radius-sm)',
        border: `1px solid ${style.color}55`,
        background: liveStatus === 'BREACHED' ? 'var(--its-signal-red-bg)' : 'var(--its-bg-subsurface)',
      }}
    >
      <div
        style={{
          fontSize: '10px', textTransform: 'uppercase', fontWeight: 700,
          color: 'var(--its-text-muted)', letterSpacing: '0.05em',
        }}
      >
        {title}
      </div>

      <div className="mono" style={{ fontSize: 'var(--text-md)', fontWeight: 700, color: style.color }}>
        {style.label}
      </div>

      {target ? (
        <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-secondary)', marginTop: '4px' }}>
          {liveElapsed !== null ? `${formatAge(liveElapsed)} elapsed` : '—'}
          {' / '}{formatAge(target)} target
          {remaining !== null && liveStatus === 'RUNNING' && (
            <div style={{ color: remaining < 60 ? 'var(--its-signal-yellow)' : 'var(--its-text-muted)' }}>
              {formatAge(Math.max(0, remaining))} remaining
            </div>
          )}
        </div>
      ) : (
        <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}>
          No target was set for this severity.
        </div>
      )}
    </div>
  );
};

const TimelineEntry: React.FC<{ entry: any }> = ({ entry }) => {
  const age = useTickingAge(entry.timestamp);
  const isCorrection = entry.entry_type === 'CORRECTION';
  const isBreach = entry.entry_type === 'SLA_BREACH';

  return (
    <div
      style={{
        display: 'flex', gap: '10px', padding: '8px 10px',
        borderLeft: `2px solid ${
          isBreach ? 'var(--its-signal-red)'
            : isCorrection ? 'var(--its-signal-yellow)'
              : 'var(--its-border-default)'
        }`,
        background: 'var(--its-bg-subsurface)',
        borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: '7px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span
            className="mono"
            style={{
              fontSize: '9px', fontWeight: 700, padding: '1px 5px',
              borderRadius: 'var(--radius-xs)',
              background: 'var(--its-bg-elevated)',
              border: '1px solid var(--its-border-subtle)',
              color: isBreach ? 'var(--its-signal-red)' : 'var(--its-text-muted)',
            }}
          >
            {entry.entry_type}
          </span>
          <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600 }}>{entry.summary}</span>
        </div>

        {entry.detail && (
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '3px', lineHeight: 1.5 }}>
            {entry.detail}
          </div>
        )}

        {isCorrection && entry.corrects_entry_id && (
          <div className="mono" style={{ fontSize: '9px', color: 'var(--its-signal-yellow)', marginTop: '3px' }}>
            CORRECTS ENTRY {entry.corrects_entry_id.slice(0, 8)}
          </div>
        )}

        <div
          className="mono"
          style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '4px' }}
          title={formatTimestamp(entry.timestamp)}
        >
          {formatAge(age)} ago · {entry.actor}
        </div>
      </div>
    </div>
  );
};

export const IncidentLifecyclePanel: React.FC<{
  incidentId: string | null;
  onChanged?: () => void;
}> = ({ incidentId, onChanged }) => {
  const [sla, setSla] = useState<any>(null);
  const [timeline, setTimeline] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [assignee, setAssignee] = useState('');

  const load = useCallback(async () => {
    if (!incidentId) return;
    setLoading(true);
    try {
      const [slaRes, timelineRes, evidenceRes] = await Promise.all([
        api.getIncidentSla(incidentId).catch(() => null),
        api.getIncidentTimeline(incidentId).catch(() => null),
        api.getIncidentEvidence(incidentId).catch(() => null),
      ]);
      setSla(slaRes);
      setTimeline(timelineRes);
      setEvidence(evidenceRes);
    } finally {
      setLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    setReport(null);
    load();
  }, [load]);

  if (!incidentId) return null;

  const acknowledge = async () => {
    setBusy(true);
    try {
      await api.acknowledgeIncident(incidentId);
      await load();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const assign = async () => {
    if (!assignee.trim()) return;
    setBusy(true);
    try {
      await api.assignIncident(incidentId, assignee.trim());
      setAssignee('');
      await load();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const generateReport = async () => {
    setBusy(true);
    try {
      setReport(await api.getIncidentReport(incidentId));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      {/* SLA -------------------------------------------------------------- */}
      <div>
        <div
          style={{
            fontSize: '10px', fontWeight: 700, letterSpacing: '0.06em',
            textTransform: 'uppercase', color: 'var(--its-text-muted)', marginBottom: '6px',
            display: 'flex', alignItems: 'center', gap: '6px',
          }}
        >
          <Timer size={11} />
          <span>Service Level</span>
        </div>

        {loading && !sla ? (
          <SkeletonRows rows={1} label="SLA status" />
        ) : sla ? (
          <>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <SlaClock
                title="Acknowledge"
                clock={sla.acknowledge}
                detectedAt={report?.incident?.detected_at ?? null}
              />
              <SlaClock
                title="Resolve"
                clock={sla.resolve}
                detectedAt={report?.incident?.detected_at ?? null}
              />
            </div>
            {sla.policy_note && (
              <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.5 }}>
                {sla.policy_note}
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* Triage actions --------------------------------------------------- */}
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
        <button onClick={acknowledge} className="its-btn" disabled={busy} style={{ padding: '3px 9px' }}>
          <CheckCircle2 size={11} />
          <span>Acknowledge</span>
        </button>
        <input
          className="its-input"
          value={assignee}
          onChange={e => setAssignee(e.target.value)}
          placeholder="Assign to…"
          aria-label="Assignee"
          style={{ width: '140px' }}
        />
        <button onClick={assign} className="its-btn" disabled={busy || !assignee.trim()} style={{ padding: '3px 9px' }}>
          <UserCheck size={11} />
          <span>Assign</span>
        </button>
        <button onClick={generateReport} className="its-btn" disabled={busy} style={{ padding: '3px 9px' }}>
          <FileText size={11} />
          <span>Report</span>
        </button>
      </div>

      {/* Evidence --------------------------------------------------------- */}
      <div>
        <div
          style={{
            fontSize: '10px', fontWeight: 700, letterSpacing: '0.06em',
            textTransform: 'uppercase', color: 'var(--its-text-muted)', marginBottom: '6px',
            display: 'flex', alignItems: 'center', gap: '6px',
          }}
        >
          <Paperclip size={11} />
          <span>Evidence ({evidence?.count ?? 0})</span>
        </div>

        {!evidence || evidence.count === 0 ? (
          <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
            NO EVIDENCE ATTACHED
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {evidence.evidence.map((item: any) => (
              <div
                key={item.id}
                style={{
                  padding: '7px 9px', borderRadius: 'var(--radius-xs)',
                  background: 'var(--its-bg-subsurface)', fontSize: 'var(--text-2xs)',
                }}
              >
                <span className="mono" style={{ fontWeight: 700 }}>{item.evidence_type}</span>
                <span style={{ color: 'var(--its-text-muted)' }}>
                  {' '}from {item.source_table} · {formatTimestamp(item.observed_at)}
                </span>
                {item.note && <div style={{ marginTop: '3px' }}>{item.note}</div>}
              </div>
            ))}
          </div>
        )}
        {evidence?.count === 0 && (
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px', lineHeight: 1.5 }}>
            Evidence must reference a record the platform stored — a camera frame it
            ingested, an observation it recorded, a command it issued.
          </div>
        )}
      </div>

      {/* Timeline --------------------------------------------------------- */}
      <div>
        <div
          style={{
            fontSize: '10px', fontWeight: 700, letterSpacing: '0.06em',
            textTransform: 'uppercase', color: 'var(--its-text-muted)', marginBottom: '6px',
            display: 'flex', alignItems: 'center', gap: '6px',
          }}
        >
          <Clock size={11} />
          <span>Timeline ({timeline?.count ?? 0}) · append-only</span>
        </div>

        {loading && !timeline ? (
          <SkeletonRows rows={3} label="Incident timeline" />
        ) : !timeline || timeline.count === 0 ? (
          <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
            {timeline?.empty_reason ?? 'NO_TIMELINE_ENTRIES'}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {timeline.entries.map((entry: any) => (
              <TimelineEntry key={entry.id} entry={entry} />
            ))}
          </div>
        )}

        {timeline?.note && (
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.5 }}>
            {timeline.note}
          </div>
        )}
      </div>

      {/* Post-incident report --------------------------------------------- */}
      {report && (
        <div
          style={{
            padding: '11px 13px', borderRadius: 'var(--radius-md)',
            border: '1px solid var(--its-border-accent)', background: 'var(--its-fresh-bg)',
          }}
        >
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, marginBottom: '8px' }}>
            POST-INCIDENT REPORT
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: '10px' }}>
            {[
              ['Detection → ack', report.durations.detection_to_acknowledgement_sec],
              ['Detection → resolve', report.durations.detection_to_resolution_sec],
              ['Ack → resolve', report.durations.acknowledgement_to_resolution_sec],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                  {label}
                </div>
                <div className="mono" style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>
                  {value === null ? 'NOT RECORDED' : formatAge(Number(value))}
                </div>
              </div>
            ))}
          </div>

          {(report.gaps ?? []).length > 0 && (
            <div style={{ marginTop: '10px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--its-signal-yellow)', marginBottom: '4px' }}>
                GAPS IN THIS REPORT
              </div>
              <ul style={{ margin: 0, paddingLeft: '16px', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.7 }}>
                {report.gaps.map((gap: string, i: number) => <li key={i}>{gap}</li>)}
              </ul>
            </div>
          )}

          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px', lineHeight: 1.6 }}>
            {report.report_basis}
          </div>
        </div>
      )}
    </div>
  );
};
