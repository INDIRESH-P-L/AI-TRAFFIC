import React, { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2, ClipboardList, Eye, EyeOff, FilePlus2, Lock, Plus, RefreshCw, Trash2,
} from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { formatTimestamp } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Shift Handover
 *
 * The record of what one shift passes to the next, in three parts that are
 * kept visibly distinct because conflating them is what makes handovers
 * untrustworthy:
 *
 *   GENERATED SNAPSHOT  machine-collected facts about the shift. Fixed at
 *                       creation and NOT editable, so nobody can quietly
 *                       revise what the platform recorded.
 *   OPERATOR NOTES      the human account. Fully editable until sign-off.
 *   PENDING ACTIONS     seeded from real open state, then edited by hand.
 *                       Auto-generated items are labelled as such.
 *
 * BLIND SPOTS are given their own section rather than buried in coverage
 * statistics. A quiet shift and an unwatched shift look identical on a
 * dashboard, and the difference is exactly what the next operator needs.
 *
 * After sign-off the record is frozen: the next shift may already have acted
 * on it, so it is superseded by a new handover rather than edited.
 */

interface PendingAction {
  kind: string;
  reference: string;
  summary: string;
  source: 'AUTO_GENERATED' | 'OPERATOR';
  done: boolean;
}

interface Handover {
  id: string;
  shift_start: string;
  shift_end: string;
  outgoing_operator: string | null;
  incoming_operator: string | null;
  status: 'DRAFT' | 'SIGNED_OFF' | 'ACKNOWLEDGED';
  generated_at: string | null;
  generated_snapshot: any;
  operator_notes: string | null;
  pending_actions: PendingAction[];
  signed_off_at: string | null;
  signed_off_by: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  editable: boolean;
  immutability_note: string;
}

const statusColor = (status: string): string =>
  status === 'ACKNOWLEDGED'
    ? 'var(--its-status-normal)'
    : status === 'SIGNED_OFF'
      ? 'var(--its-text-accent)'
      : 'var(--its-status-warning)';

export const ShiftHandover: React.FC = () => {
  const [list, setList] = useState<Handover[] | null>(null);
  const [selected, setSelected] = useState<Handover | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [showPreview, setShowPreview] = useState(false);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [shiftHours, setShiftHours] = useState(8);
  const [notesDraft, setNotesDraft] = useState('');
  const [newAction, setNewAction] = useState('');

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getHandovers(20);
      const items: Handover[] = data.handovers || data.items || [];
      setList(items);
      if (items.length && !selected) {
        const full = await api.getHandover(items[0].id);
        setSelected(full);
        setNotesDraft(full.operator_notes || '');
      }
    } catch (e: any) {
      setError(e?.message || 'Handover records could not be loaded.');
    } finally {
      setLoading(false);
    }
    // `selected` is deliberately excluded: re-selecting on every change would
    // discard the operator's unsaved notes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const open = async (id: string) => {
    setError(null);
    try {
      const full = await api.getHandover(id);
      setSelected(full);
      setNotesDraft(full.operator_notes || '');
    } catch (e: any) {
      setError(e?.message || 'That handover could not be opened.');
    }
  };

  const loadPreview = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.previewHandover(shiftHours);
      setPreview(data.snapshot);
      setShowPreview(true);
    } catch (e: any) {
      setError(e?.message || 'The preview could not be generated.');
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createHandover({ shift_hours: shiftHours });
      setSelected(created);
      setNotesDraft(created.operator_notes || '');
      setNotice('Draft created. The snapshot is fixed; notes and actions are yours to edit.');
      await loadList();
    } catch (e: any) {
      setError(e?.message || 'The handover could not be created.');
    } finally {
      setBusy(false);
    }
  };

  const save = async (patch: Record<string, unknown>) => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateHandover(selected.id, patch);
      setSelected(updated);
      setNotesDraft(updated.operator_notes || '');
      setNotice('Saved.');
    } catch (e: any) {
      setError(e?.message || 'The change could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const signOff = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      // Unsaved notes are committed first: signing off freezes the record, and
      // losing the operator's last paragraph to a race is not acceptable.
      if (notesDraft !== (selected.operator_notes || '')) {
        await api.updateHandover(selected.id, { operator_notes: notesDraft });
      }
      const signed = await api.signOffHandover(selected.id);
      setSelected(signed);
      setNotice('Signed off and frozen. Create a new handover rather than revising this one.');
      await loadList();
    } catch (e: any) {
      setError(e?.message || 'Sign-off failed.');
    } finally {
      setBusy(false);
    }
  };

  const acknowledge = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const acked = await api.acknowledgeHandover(selected.id);
      setSelected(acked);
      setNotice('Acknowledged. The incoming shift has taken the network.');
      await loadList();
    } catch (e: any) {
      setError(e?.message || 'Acknowledgement failed.');
    } finally {
      setBusy(false);
    }
  };

  const toggleAction = (index: number) => {
    if (!selected?.editable) return;
    const actions = selected.pending_actions.map((a, i) =>
      i === index ? { ...a, done: !a.done } : a,
    );
    void save({ pending_actions: actions });
  };

  const addAction = () => {
    if (!selected?.editable || !newAction.trim()) return;
    const actions = [
      ...selected.pending_actions,
      {
        kind: 'OPERATOR_NOTE',
        reference: 'manual',
        summary: newAction.trim(),
        source: 'OPERATOR' as const,
        done: false,
      },
    ];
    setNewAction('');
    void save({ pending_actions: actions });
  };

  const removeAction = (index: number) => {
    if (!selected?.editable) return;
    void save({
      pending_actions: selected.pending_actions.filter((_, i) => i !== index),
    });
  };

  return (
    <div className="its-page">
      <div className="its-page-header">
        <div>
          <h1 className="its-page-title">
            <ClipboardList size={18} /> Shift Handover
          </h1>
          <p className="its-page-subtitle">
            What this shift saw, what it could not see, and what the next shift has to pick up.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <select
            className="its-select"
            value={shiftHours}
            onChange={(e) => setShiftHours(Number(e.target.value))}
          >
            <option value={8}>8-hour shift</option>
            <option value={12}>12-hour shift</option>
            <option value={6}>6-hour shift</option>
            <option value={24}>24 hours</option>
          </select>
          <button className="its-btn its-btn-sm" onClick={() => void loadPreview()} disabled={busy}>
            {showPreview ? <EyeOff size={13} /> : <Eye size={13} />} Preview
          </button>
          <button className="its-btn its-btn-primary its-btn-sm" onClick={() => void create()} disabled={busy}>
            <FilePlus2 size={13} /> New handover
          </button>
        </div>
      </div>

      {error && (
        <div
          className="its-panel"
          style={{ padding: '11px 14px', marginBottom: '12px', fontSize: '11px', color: 'var(--its-status-critical)' }}
        >
          {error}
        </div>
      )}
      {notice && !error && (
        <div
          className="its-panel"
          style={{ padding: '11px 14px', marginBottom: '12px', fontSize: '11px', color: 'var(--its-text-secondary)' }}
        >
          {notice}
        </div>
      )}

      {/* The preview is explicitly marked as storing nothing. An operator
          checking what a handover would say must not accidentally file one. */}
      {showPreview && preview && (
        <div className="its-panel" style={{ marginBottom: '14px' }}>
          <div className="its-panel-header">
            <span>PREVIEW - NOT SAVED</span>
            <button className="its-btn its-btn-sm" onClick={() => setShowPreview(false)}>
              Dismiss
            </button>
          </div>
          <div style={{ padding: '10px 14px', fontSize: '10px', color: 'var(--its-text-muted)' }}>
            This is what a handover generated now would contain. Nothing has been recorded.
          </div>
          <SnapshotView snapshot={preview} />
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 300px) minmax(0, 1fr)', gap: '14px' }}>
        {/* History */}
        <div className="its-panel" style={{ alignSelf: 'start' }}>
          <div className="its-panel-header">
            <span>HANDOVERS</span>
            <button className="its-btn its-btn-sm" onClick={() => void loadList()}>
              <RefreshCw size={12} />
            </button>
          </div>
          {loading ? (
            <SkeletonRows rows={4} label="Loading handovers" />
          ) : !list?.length ? (
            <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-text-muted)', lineHeight: 1.6 }}>
              NO HANDOVERS RECORDED. Create one at the end of a shift to capture what the platform
              observed and what it could not see.
            </div>
          ) : (
            <div>
              {list.map((item) => (
                <button
                  key={item.id}
                  onClick={() => void open(item.id)}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '10px 14px',
                    border: 'none',
                    borderBottom: '1px solid var(--its-border-subtle)',
                    background:
                      selected?.id === item.id ? 'var(--its-bg-elevated)' : 'transparent',
                    cursor: 'pointer',
                    color: 'inherit',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 600 }}>
                      {formatTimestamp(item.shift_start)}
                    </span>
                    <span
                      style={{
                        fontSize: '9px',
                        fontWeight: 700,
                        letterSpacing: '0.04em',
                        color: statusColor(item.status),
                      }}
                    >
                      {item.status.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
                    {item.outgoing_operator || 'unattributed'}
                    {item.incoming_operator ? ` to ${item.incoming_operator}` : ''}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Selected record */}
        <div>
          {!selected ? (
            <TruthfulEmptyState
              title="NO HANDOVER SELECTED"
              description="Select a handover from the list, or create one for the shift just ending. The generated snapshot is collected from recorded state - incidents, provider health, signal activity, and the junctions nobody could see."
            />
          ) : (
            <>
              <div className="its-panel" style={{ marginBottom: '14px' }}>
                <div className="its-panel-header">
                  <span>
                    {formatTimestamp(selected.shift_start)} - {formatTimestamp(selected.shift_end)}
                  </span>
                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      letterSpacing: '0.05em',
                      color: statusColor(selected.status),
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                    }}
                  >
                    {!selected.editable && <Lock size={11} />}
                    {selected.status.replace(/_/g, ' ')}
                  </span>
                </div>

                <div
                  style={{
                    padding: '10px 14px',
                    fontSize: '10px',
                    color: 'var(--its-text-muted)',
                    lineHeight: 1.6,
                    borderBottom: '1px solid var(--its-border-subtle)',
                  }}
                >
                  {selected.immutability_note}
                  {selected.signed_off_by && (
                    <div style={{ marginTop: '4px' }}>
                      Signed off by <strong>{selected.signed_off_by}</strong> at{' '}
                      {formatTimestamp(selected.signed_off_at)}.
                    </div>
                  )}
                  {selected.acknowledged_by && (
                    <div style={{ marginTop: '2px' }}>
                      Acknowledged by <strong>{selected.acknowledged_by}</strong> at{' '}
                      {formatTimestamp(selected.acknowledged_at)}.
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', gap: '8px', padding: '11px 14px' }}>
                  {selected.status === 'DRAFT' && (
                    <button className="its-btn its-btn-primary its-btn-sm" onClick={() => void signOff()} disabled={busy}>
                      <CheckCircle2 size={13} /> Sign off &amp; freeze
                    </button>
                  )}
                  {selected.status === 'SIGNED_OFF' && (
                    <button className="its-btn its-btn-primary its-btn-sm" onClick={() => void acknowledge()} disabled={busy}>
                      <CheckCircle2 size={13} /> Acknowledge as incoming operator
                    </button>
                  )}
                  {selected.status === 'ACKNOWLEDGED' && (
                    <span style={{ fontSize: '11px', color: 'var(--its-status-normal)' }}>
                      Handover complete.
                    </span>
                  )}
                </div>
              </div>

              {/* Operator notes */}
              <div className="its-panel" style={{ marginBottom: '14px' }}>
                <div className="its-panel-header">
                  <span>OPERATOR NOTES</span>
                  {selected.editable && notesDraft !== (selected.operator_notes || '') && (
                    <button className="its-btn its-btn-sm" onClick={() => void save({ operator_notes: notesDraft })} disabled={busy}>
                      Save notes
                    </button>
                  )}
                </div>
                <div style={{ padding: '12px 14px' }}>
                  {selected.editable ? (
                    <textarea
                      className="its-input"
                      style={{ width: '100%', minHeight: '110px', fontFamily: 'inherit', lineHeight: 1.6 }}
                      placeholder="What the numbers do not say: roadworks, crew movements, anything the next operator should know."
                      value={notesDraft}
                      onChange={(e) => setNotesDraft(e.target.value)}
                    />
                  ) : (
                    <div style={{ fontSize: '11px', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                      {selected.operator_notes || (
                        <span style={{ color: 'var(--its-text-muted)' }}>
                          No notes were recorded for this shift.
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Pending actions */}
              <div className="its-panel" style={{ marginBottom: '14px' }}>
                <div className="its-panel-header">
                  <span>PENDING ACTIONS ({selected.pending_actions.filter((a) => !a.done).length} OPEN)</span>
                </div>

                {selected.pending_actions.length === 0 ? (
                  <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
                    Nothing outstanding was detected, and nothing has been added by hand.
                  </div>
                ) : (
                  selected.pending_actions.map((action, index) => (
                    <div
                      key={`${action.kind}-${index}`}
                      style={{
                        display: 'flex',
                        gap: '9px',
                        alignItems: 'flex-start',
                        padding: '9px 14px',
                        borderBottom: '1px solid var(--its-border-subtle)',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={action.done}
                        disabled={!selected.editable || busy}
                        onChange={() => toggleAction(index)}
                        style={{ marginTop: '2px' }}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            fontSize: '11px',
                            textDecoration: action.done ? 'line-through' : 'none',
                            color: action.done ? 'var(--its-text-muted)' : 'inherit',
                          }}
                        >
                          {action.summary}
                        </div>
                        <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
                          {action.kind.replace(/_/g, ' ')}
                          {' - '}
                          {action.source === 'AUTO_GENERATED'
                            ? 'detected by the platform'
                            : 'added by an operator'}
                        </div>
                      </div>
                      {selected.editable && action.source === 'OPERATOR' && (
                        <button
                          className="its-btn its-btn-sm"
                          onClick={() => removeAction(index)}
                          title="Remove this item"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                  ))
                )}

                {selected.editable && (
                  <div style={{ display: 'flex', gap: '8px', padding: '11px 14px' }}>
                    <input
                      className="its-input"
                      style={{ flex: 1 }}
                      placeholder="Add an item for the next shift"
                      value={newAction}
                      onChange={(e) => setNewAction(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') addAction();
                      }}
                    />
                    <button className="its-btn its-btn-sm" onClick={addAction} disabled={busy || !newAction.trim()}>
                      <Plus size={13} /> Add
                    </button>
                  </div>
                )}
              </div>

              {/* Generated snapshot - never editable */}
              <div className="its-panel">
                <div className="its-panel-header">
                  <span>GENERATED SNAPSHOT</span>
                  <span
                    style={{
                      fontSize: '9px',
                      color: 'var(--its-text-muted)',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <Lock size={10} /> FIXED AT CREATION
                  </span>
                </div>
                <SnapshotView snapshot={selected.generated_snapshot} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

// ===========================================================================
// Snapshot rendering
// ===========================================================================

const Stat: React.FC<{ label: string; value: React.ReactNode; muted?: boolean }> = ({
  label,
  value,
  muted,
}) => (
  <div>
    <div className="its-metric-label">{label}</div>
    <div
      className="mono"
      style={{
        fontSize: '19px',
        fontWeight: 800,
        color: muted ? 'var(--its-text-muted)' : 'var(--its-text-primary)',
      }}
    >
      {value}
    </div>
  </div>
);

// Exported so `npm run check:render` can render it against a recorded snapshot.
// This is the section most likely to be read under time pressure at a shift
// change, and the one where a null rendered as 0 would do the most damage.
export const SnapshotView: React.FC<{ snapshot: any }> = ({ snapshot }) => {
  if (!snapshot) {
    return (
      <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
        NO SNAPSHOT RECORDED.
      </div>
    );
  }

  const { incidents, alerts, providers, signal_activity, data_coverage, blind_spots } = snapshot;

  return (
    <div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '24px',
          padding: '14px',
          borderBottom: '1px solid var(--its-border-subtle)',
        }}
      >
        <Stat label="OPEN INCIDENTS" value={incidents?.open_count ?? '--'} />
        <Stat label="RAISED THIS SHIFT" value={incidents?.raised_this_shift ?? '--'} />
        <Stat label="RESOLVED" value={incidents?.resolved_this_shift ?? '--'} />
        <Stat label="UNACK ALERTS" value={alerts?.unacknowledged_count ?? '--'} />
        <Stat label="COMMANDS EXECUTED" value={signal_activity?.commands_executed ?? '--'} />
        <Stat
          label="REJECTED BY SAFETY ENGINE"
          value={signal_activity?.rejected_by_safety_engine ?? '--'}
        />
      </div>

      {/* Data coverage: the mean is over rated junctions only. */}
      {data_coverage && (
        <div style={{ padding: '14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
          <div className="its-metric-label" style={{ marginBottom: '9px' }}>
            DATA COVERAGE
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '24px' }}>
            <Stat
              label="MEAN TRUST (RATED ONLY)"
              value={
                data_coverage.network_trust_mean_of_rated === null
                  ? '--'
                  : data_coverage.network_trust_mean_of_rated.toFixed(1)
              }
              muted={data_coverage.network_trust_mean_of_rated === null}
            />
            <Stat label="RATED JUNCTIONS" value={data_coverage.rated_junctions ?? '--'} />
            <Stat label="UNRATED" value={data_coverage.unrated_junctions ?? '--'} muted />
            <Stat label="AI-GATED" value={data_coverage.ai_gated_count ?? '--'} />
          </div>
        </div>
      )}

      {/* Blind spots get their own section on purpose. */}
      {blind_spots && (
        <div
          style={{
            padding: '14px',
            borderBottom: '1px solid var(--its-border-subtle)',
            background: blind_spots.count ? 'var(--its-bg-elevated)' : 'transparent',
          }}
        >
          <div className="its-metric-label" style={{ marginBottom: '6px' }}>
            COVERAGE GAPS - {blind_spots.total_blind_count ?? 0} UNSEEN,{' '}
            {blind_spots.partially_blind_count ?? 0} PARTIAL, OF{' '}
            {blind_spots.total_junctions} JUNCTION(S)
          </div>
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', lineHeight: 1.7, marginBottom: '9px' }}>
            {blind_spots.why_this_matters}
          </div>
          {blind_spots.count === 0 ? (
            <div style={{ fontSize: '11px', color: 'var(--its-status-normal)' }}>
              Every junction reported on every channel this shift.
            </div>
          ) : (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Junction</th>
                    <th style={{ width: '82px' }}>Severity</th>
                    <th style={{ width: '110px' }}>Observations</th>
                    <th>What was missing</th>
                  </tr>
                </thead>
                <tbody>
                  {/* Unseen junctions sort first: a junction that went dark is
                      the one to act on, not one that simply has no loops. */}
                  {[...blind_spots.items]
                    .sort((a: any, b: any) =>
                      (a.severity === 'TOTAL' ? 0 : 1) - (b.severity === 'TOTAL' ? 0 : 1),
                    )
                    .map((item: any) => (
                      <tr key={item.intersection_id}>
                        <td style={{ fontWeight: 600 }}>{item.name}</td>
                        <td>
                          <span
                            style={{
                              fontSize: '9px',
                              fontWeight: 700,
                              letterSpacing: '0.04em',
                              color:
                                item.severity === 'TOTAL'
                                  ? 'var(--its-status-critical)'
                                  : 'var(--its-status-warning)',
                            }}
                          >
                            {item.severity === 'TOTAL' ? 'UNSEEN' : 'PARTIAL'}
                          </span>
                        </td>
                        <td className="mono">
                          {item.observations_this_shift} obs / {item.signal_readings_this_shift} state
                        </td>
                        <td style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                          {item.reasons.join('; ')}
                          {item.observed_channels?.length > 0 && (
                            <div style={{ color: 'var(--its-text-secondary)', marginTop: '2px' }}>
                              Did report: {item.observed_channels.join(', ')}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Providers */}
      {providers && (
        <div style={{ padding: '14px' }}>
          <div className="its-metric-label" style={{ marginBottom: '9px' }}>
            PROVIDERS - {providers.degraded_count} DEGRADED OF {providers.total_known}
          </div>
          {providers.degraded?.length ? (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th style={{ width: '100px' }}>State</th>
                    <th style={{ width: '90px' }}>Circuit</th>
                    <th>Last error</th>
                  </tr>
                </thead>
                <tbody>
                  {providers.degraded.map((p: any) => (
                    <tr key={p.label}>
                      <td style={{ fontWeight: 600 }}>{p.label}</td>
                      <td style={{ color: 'var(--its-status-critical)', fontSize: '10px' }}>{p.state}</td>
                      <td className="mono" style={{ fontSize: '10px' }}>{p.circuit_state}</td>
                      <td style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                        {p.last_error || 'no detail recorded'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ fontSize: '11px', color: 'var(--its-text-muted)' }}>
              No provider was degraded during this shift.
            </div>
          )}
          {providers.unprobed_note && (
            <div style={{ fontSize: '10px', color: 'var(--its-status-warning)', marginTop: '9px', lineHeight: 1.6 }}>
              {providers.unprobed_note}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
