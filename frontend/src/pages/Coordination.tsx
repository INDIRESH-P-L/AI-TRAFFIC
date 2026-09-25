import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { GitMerge, Play, RefreshCw, ScanSearch } from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import {
  CoordinationPlanPanel, CoordinationVerifyPanel,
} from '../components/coordination/CoordinationPlanPanel';
import { formatTimestamp } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Arterial Coordination
 *
 * Propose a green wave, see what the Safety Engine says about every controller,
 * apply it, then check it against what the stringline observes.
 *
 * States:
 *   LOADING  skeleton rows while proposing or loading; no numbers.
 *   EMPTY    no corridors -> TruthfulEmptyState. A corridor that cannot be
 *            coordinated is not an empty state: the backend's NOT_COMPUTABLE /
 *            REFUSED verdict renders with every junction's reason.
 *   ERROR    named failure; a 403 on apply names the missing scope. A failed
 *            request never leaves a previous plan on screen looking current.
 *
 * Volumes are entered per junction. Left blank, the planner uses measured
 * demand (subject to the data-quality trust gate) - it never splits evenly as
 * a guess.
 */

const EMPTY_VOLUMES = { main: '', cross: '', lanes: '2' };

interface Volumes {
  [intersectionId: string]: { main: string; cross: string; lanes: string };
}

export const Coordination: React.FC = () => {
  const [corridors, setCorridors] = useState<any[] | null>(null);
  const [corridorId, setCorridorId] = useState('');
  const [speed, setSpeed] = useState('');
  const [cycle, setCycle] = useState('');
  const [direction, setDirection] = useState('ASCENDING');
  const [volumes, setVolumes] = useState<Volumes>({});

  const [plans, setPlans] = useState<any[]>([]);
  const [plan, setPlan] = useState<any>(null);
  const [verify, setVerify] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const corridor = useMemo(() => corridors?.find((c) => c.id === corridorId), [corridors, corridorId]);

  useEffect(() => {
    let cancelled = false;
    api
      .getCorridors()
      .then((list: any[]) => {
        if (cancelled) return;
        setCorridors(list);
        if (list.length) setCorridorId((current) => current || list[0].id);
      })
      .catch((e: any) => !cancelled && setError(e?.message || 'Corridors could not be loaded.'));
    return () => {
      cancelled = true;
    };
  }, []);

  const loadPlans = useCallback(async () => {
    if (!corridorId) return;
    try {
      const data = await api.getCoordinationPlans(corridorId);
      setPlans(data.plans || []);
    } catch (e: any) {
      setError(e?.message || 'Plans could not be loaded.');
    }
  }, [corridorId]);

  useEffect(() => {
    setPlan(null);
    setVerify(null);
    void loadPlans();
  }, [loadPlans]);

  const setVolume = (id: string, field: 'main' | 'cross' | 'lanes', value: string) =>
    setVolumes((current) => ({
      ...current,
      [id]: { ...EMPTY_VOLUMES, ...current[id], [field]: value },
    }));

  const propose = async () => {
    setBusy(true);
    setError(null);
    setPlan(null);
    setVerify(null);
    const movements: Record<string, any[]> = {};
    for (const junction of corridor?.intersections || []) {
      const entry = volumes[junction.id];
      if (entry && entry.main && entry.cross) {
        movements[junction.id] = [
          { phase_number: 2, volume_vph: Number(entry.main), lanes: Number(entry.lanes || 1) },
          { phase_number: 4, volume_vph: Number(entry.cross), lanes: 1 },
        ];
      }
    }
    try {
      const result = await api.proposeCoordination(corridorId, {
        direction,
        design_speed_kph: speed ? Number(speed) : null,
        cycle_sec: cycle ? Number(cycle) : null,
        movements,
      });
      setPlan(result);
      await loadPlans();
    } catch (e: any) {
      setError(e?.message || 'The plan could not be computed.');
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!plan?.plan_id) return;
    setBusy(true);
    setError(null);
    try {
      setPlan(await api.applyCoordinationPlan(plan.plan_id));
      await loadPlans();
    } catch (e: any) {
      setError(
        e?.message?.includes('403')
          ? 'Applying a timing plan requires the signal:configure scope (engineer or administrator). Nothing was sent.'
          : e?.message || 'Apply failed.',
      );
    } finally {
      setBusy(false);
    }
  };

  const runVerify = async () => {
    if (!plan?.plan_id) return;
    setBusy(true);
    try {
      setVerify(await api.verifyCoordinationPlan(plan.plan_id));
    } catch (e: any) {
      setError(e?.message || 'Verification failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="its-page">
      <div className="its-page-header">
        <div>
          <h1 className="its-page-title">
            <GitMerge size={18} /> Arterial Coordination
          </h1>
          <p className="its-page-subtitle">
            Green-wave timing from corridor geometry and demand, validated by the Safety Engine,
            written to controllers, then checked against what the stringline observes.
          </p>
        </div>
        <select className="its-select" value={corridorId} onChange={(e) => setCorridorId(e.target.value)}
                disabled={!corridors?.length}>
          {!corridors?.length && <option value="">No corridors</option>}
          {corridors?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      {corridors && corridors.length === 0 && (
        <TruthfulEmptyState
          title="NO CORRIDORS CONFIGURED"
          description="A green wave coordinates at least two signalised junctions along a corridor. Define a corridor and connect NTCIP 1202 controllers to its junctions."
          actionText="Configure corridors"
          actionLink="/corridors"
        />
      )}

      {corridor && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 340px) minmax(0, 1fr)', gap: '14px' }}>
          <div>
            <div className="its-panel">
              <div className="its-panel-header"><span>PROPOSE A PLAN</span></div>
              <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <label style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                  DESIGN SPEED (KM/H)
                  <input className="its-input" style={{ width: '100%', marginTop: '4px' }} type="number"
                         placeholder="Blank = configured speed limit" value={speed}
                         onChange={(e) => setSpeed(e.target.value)} />
                </label>
                <label style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                  COMMON CYCLE (S)
                  <input className="its-input" style={{ width: '100%', marginTop: '4px' }} type="number"
                         placeholder="Blank = critical junction's Webster optimum" value={cycle}
                         onChange={(e) => setCycle(e.target.value)} />
                </label>
                <label style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                  DIRECTION
                  <select className="its-select" style={{ width: '100%', marginTop: '4px' }} value={direction}
                          onChange={(e) => setDirection(e.target.value)}>
                    <option value="ASCENDING">Ascending ({corridor.intersections?.[0]?.name} first)</option>
                    <option value="DESCENDING">Descending</option>
                  </select>
                </label>

                <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}>
                  VOLUMES (VEH/H) - blank uses measured demand
                </div>
                {(corridor.intersections || []).map((junction: any) => (
                  <div key={junction.id} style={{ fontSize: '10px' }}>
                    <div style={{ fontWeight: 600, marginBottom: '3px' }}>{junction.name}</div>
                    <div style={{ display: 'flex', gap: '5px' }}>
                      <input className="its-input its-input-sm" style={{ flex: 1 }} type="number"
                             placeholder="Main (ph 2)" value={volumes[junction.id]?.main || ''}
                             onChange={(e) => setVolume(junction.id, 'main', e.target.value)} />
                      <input className="its-input its-input-sm" style={{ width: '52px' }} type="number"
                             placeholder="lanes" value={volumes[junction.id]?.lanes || ''}
                             onChange={(e) => setVolume(junction.id, 'lanes', e.target.value)} />
                      <input className="its-input its-input-sm" style={{ flex: 1 }} type="number"
                             placeholder="Cross (ph 4)" value={volumes[junction.id]?.cross || ''}
                             onChange={(e) => setVolume(junction.id, 'cross', e.target.value)} />
                    </div>
                  </div>
                ))}

                <button className="its-btn its-btn-primary" onClick={() => void propose()} disabled={busy}>
                  <GitMerge size={13} /> {busy ? 'Working...' : 'Propose plan'}
                </button>
                <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', lineHeight: 1.6 }}>
                  Proposing validates every controller with the Safety Engine and sends nothing.
                </div>
              </div>
            </div>

            <div className="its-panel" style={{ marginTop: '14px' }}>
              <div className="its-panel-header">
                <span>PLAN HISTORY</span>
                <button className="its-btn its-btn-sm" onClick={() => void loadPlans()}><RefreshCw size={12} /></button>
              </div>
              {plans.length === 0 ? (
                <div style={{ padding: '12px 14px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
                  NO PLAN HAS BEEN PROPOSED FOR THIS CORRIDOR.
                </div>
              ) : (
                plans.map((p) => (
                  <button key={p.plan_id} onClick={() => { setPlan(p); setVerify(null); }}
                          style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 14px',
                                   border: 'none', borderBottom: '1px solid var(--its-border-subtle)',
                                   background: plan?.plan_id === p.plan_id ? 'var(--its-bg-elevated)' : 'transparent',
                                   color: 'inherit', cursor: 'pointer', fontSize: '10px' }}>
                    <span className="mono">{formatTimestamp(p.created_at)}</span>
                    <span style={{ float: 'right', fontWeight: 700 }}>{p.status.replace(/_/g, ' ')}</span>
                    <div style={{ color: 'var(--its-text-muted)' }}>{p.cycle_sec}s · {p.design_speed_kph} km/h</div>
                  </button>
                ))
              )}
            </div>
          </div>

          <div>
            {error && (
              <div className="its-panel" style={{ padding: '12px 14px', marginBottom: '12px', fontSize: '11px', color: 'var(--its-signal-red)' }}>
                {error}
              </div>
            )}
            {busy && !plan && <SkeletonRows rows={6} label="Computing and validating the plan" />}
            {!busy && !plan && !error && (
              <TruthfulEmptyState
                title="NO PLAN SELECTED"
                description="Propose a plan or select one from the history. A plan is computed from corridor geometry, the design speed and junction demand, and every controller's part is validated by the Safety Engine before it can be applied."
              />
            )}
            {plan && <CoordinationPlanPanel plan={plan} />}
            {plan?.status === 'PROPOSED' && (
              <div className="its-panel" style={{ marginTop: '12px', padding: '12px 14px' }}>
                <button className="its-btn its-btn-primary" onClick={() => void apply()} disabled={busy}>
                  <Play size={13} /> Apply to controllers
                </button>
                <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.6 }}>
                  Every controller is re-validated first; if any would now refuse, nothing is sent to any of
                  them. Each write is read back, and a controller whose read-back differs is recorded as failed.
                </div>
              </div>
            )}
            {(plan?.status === 'APPLIED' || plan?.status === 'PARTIALLY_APPLIED') && (
              <div style={{ marginTop: '12px' }}>
                <button className="its-btn" onClick={() => void runVerify()} disabled={busy}>
                  <ScanSearch size={13} /> Verify against the stringline
                </button>
                {verify && <div style={{ marginTop: '10px' }}><CoordinationVerifyPanel result={verify} /></div>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
