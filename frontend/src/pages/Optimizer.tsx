import React, { useCallback, useEffect, useState } from 'react';
import {
  Beaker, Calculator, FlaskConical, Plus, ShieldCheck, ShieldX, Trash2, TrendingDown,
} from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { formatTimestamp } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Signal Timing Optimiser & Scenario Sandbox
 *
 * Two tools on one page, kept visually apart because confusing them is the
 * failure mode that matters:
 *
 *   OPTIMISE  produces a proposal meant to be acted on. It carries a Safety
 *             Engine verdict and cannot be applied if that verdict fails.
 *   SCENARIO  produces a hypothetical. It is banded, stamped, and has no
 *             path to a controller at all.
 *
 * The calculation trace is shown in full for both. An engineer checking
 * Webster's arithmetic is the intended reader, not a decoration.
 */

type Mode = 'OPTIMISE' | 'SCENARIO';

interface MovementRow {
  phase_number: number;
  name: string;
  volume_vph: string;
  lanes: number;
  min_green_sec: number;
  max_green_sec: number;
}

const emptyMovement = (phase: number): MovementRow => ({
  phase_number: phase,
  name: `Phase ${phase}`,
  volume_vph: '',
  lanes: 1,
  min_green_sec: 7,
  max_green_sec: 65,
});

const TraceTable: React.FC<{ trace: any[] }> = ({ trace }) => (
  <div className="its-table-container" style={{ marginTop: '10px' }}>
    <table className="its-table">
      <thead>
        <tr>
          <th style={{ width: '64px' }}>Symbol</th>
          <th>Quantity</th>
          <th>Value</th>
          <th>Formula</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        {trace.map((step, i) => (
          <tr key={i}>
            <td className="mono" style={{ fontWeight: 700, color: 'var(--its-text-accent)' }}>
              {step.symbol}
            </td>
            <td>{step.label}</td>
            <td className="mono">
              {typeof step.value === 'object' && step.value !== null
                ? JSON.stringify(step.value)
                : String(step.value)}
            </td>
            <td className="mono" style={{ fontSize: '10px' }}>{step.formula}</td>
            <td style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>{step.source}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const SplitsTable: React.FC<{ splits: any[] }> = ({ splits }) => (
  <div className="its-table-container" style={{ marginTop: '10px' }}>
    <table className="its-table">
      <thead>
        <tr>
          <th>Phase</th>
          <th>Green</th>
          <th>Capacity</th>
          <th>v/c</th>
          <th>Delay</th>
          <th>Volume source</th>
        </tr>
      </thead>
      <tbody>
        {splits.map(split => (
          <tr key={split.phase}>
            <td>
              <span className="mono" style={{ fontWeight: 700 }}>Ø{split.phase}</span>
              <span style={{ color: 'var(--its-text-muted)' }}> {split.name}</span>
            </td>
            <td className="mono">{split.effective_green_sec}s</td>
            <td className="mono">{split.capacity_vph} veh/h</td>
            <td
              className="mono"
              style={{
                fontWeight: 700,
                color:
                  split.v_over_c_status === 'OVER_CAPACITY' ? 'var(--its-signal-red)'
                    : split.v_over_c_status === 'APPROACHING_CAPACITY' ? 'var(--its-signal-yellow)'
                      : 'var(--its-signal-green)',
              }}
              title={split.v_over_c_status}
            >
              {split.v_over_c ?? '—'}
            </td>
            <td className="mono">
              {split.estimated_delay_sec_per_veh === null
                ? 'UNBOUNDED'
                : `${split.estimated_delay_sec_per_veh}s`}
            </td>
            <td className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              {split.volume_source}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export const Optimizer: React.FC = () => {
  const [mode, setMode] = useState<Mode>('OPTIMISE');
  const [intersections, setIntersections] = useState<any[]>([]);
  const [controllers, setControllers] = useState<any[]>([]);
  const [intersectionId, setIntersectionId] = useState('');
  const [movements, setMovements] = useState<MovementRow[]>([
    emptyMovement(2), emptyMovement(4),
  ]);
  const [useMeasured, setUseMeasured] = useState(false);
  const [label, setLabel] = useState('What if peak demand rises?');
  const [compareToMeasured, setCompareToMeasured] = useState(true);

  const [result, setResult] = useState<any>(null);
  const [scenario, setScenario] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [inters, ctrls] = await Promise.all([
        api.getIntersections().catch(() => []),
        api.getControllers().catch(() => []),
      ]);
      setIntersections(inters);
      setControllers(ctrls);
      if (inters.length > 0 && !intersectionId) setIntersectionId(inters[0].id);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!intersectionId) return;
    api.getScenarioRuns(intersectionId)
      .then(res => setHistory(res.scenarios ?? []))
      .catch(() => setHistory([]));
  }, [intersectionId, scenario]);

  // Seed the movement rows from the real controller's configured phases.
  useEffect(() => {
    const controller = controllers.find(c => c.intersection_id === intersectionId);
    if (!controller?.phases?.length) return;
    setMovements(controller.phases.map((phase: any) => ({
      phase_number: phase.phase_number,
      name: phase.name,
      volume_vph: '',
      lanes: 1,
      min_green_sec: phase.min_green,
      max_green_sec: phase.max_green,
    })));
  }, [intersectionId, controllers]);

  const movementPayload = () =>
    movements
      .filter(m => m.volume_vph !== '')
      .map(m => ({
        phase_number: m.phase_number,
        name: m.name,
        volume_vph: Number(m.volume_vph),
        lanes: m.lanes,
        min_green_sec: m.min_green_sec,
        max_green_sec: m.max_green_sec,
      }));

  const runOptimiser = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const payload: any = { intersection_id: intersectionId };
      if (!useMeasured) payload.movements = movementPayload();
      setResult(await api.recommendTiming(payload));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const runScenario = async () => {
    setBusy(true);
    setError(null);
    setScenario(null);
    try {
      setScenario(await api.runScenario({
        intersection_id: intersectionId,
        label,
        movements: movementPayload(),
        compare_to_measured: compareToMeasured,
      }));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const active = mode === 'OPTIMISE' ? result : scenario;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* Mode ------------------------------------------------------------- */}
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <Calculator size={14} color="var(--its-text-accent)" />
            <span>Signal Timing</span>
          </span>
          <div style={{ display: 'flex', gap: '6px' }}>
            {(['OPTIMISE', 'SCENARIO'] as Mode[]).map(option => (
              <button
                key={option}
                onClick={() => setMode(option)}
                className="its-btn"
                aria-pressed={mode === option}
                style={{
                  padding: '3px 10px',
                  borderColor: mode === option ? 'var(--its-border-focused)' : undefined,
                  color: mode === option ? 'var(--its-text-accent)' : undefined,
                }}
              >
                {option === 'OPTIMISE' ? <ShieldCheck size={11} /> : <FlaskConical size={11} />}
                <span>{option}</span>
              </button>
            ))}
          </div>
        </div>

        <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.7 }}>
          {mode === 'OPTIMISE' ? (
            <>
              Produces a proposal <strong>meant to be acted on</strong>. It runs Webster's
              method over real measured demand or volumes you enter, and carries a Safety
              Engine verdict. A proposal that fails that verdict cannot be applied.
            </>
          ) : (
            <>
              Produces a <strong>hypothetical</strong>. Results are stamped SCENARIO, stored
              in a separate table from observed telemetry, and have no path to a controller.
            </>
          )}
        </div>
      </div>

      {/* Inputs ----------------------------------------------------------- */}
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">Demand</span>
        </div>

        {loading ? (
          <SkeletonRows rows={2} label="Optimiser inputs" />
        ) : intersections.length === 0 ? (
          <div className="mono" style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}>
            NO JUNCTION CONFIGURED
          </div>
        ) : (
          <>
            <label style={fieldLabel} htmlFor="opt-junction">Junction</label>
            <select
              id="opt-junction"
              className="its-select"
              value={intersectionId}
              onChange={e => setIntersectionId(e.target.value)}
            >
              {intersections.map(inter => (
                <option key={inter.id} value={inter.id}>{inter.name} ({inter.code})</option>
              ))}
            </select>

            {mode === 'OPTIMISE' && (
              <label
                style={{
                  display: 'flex', alignItems: 'center', gap: '8px',
                  marginTop: '10px', fontSize: 'var(--text-2xs)',
                }}
              >
                <input
                  type="checkbox"
                  checked={useMeasured}
                  onChange={e => setUseMeasured(e.target.checked)}
                  style={{ accentColor: 'var(--its-text-accent)' }}
                />
                <span>
                  Use measured detector demand instead of entered volumes
                  <span style={{ color: 'var(--its-text-muted)' }}>
                    {' '}(requires lane-to-phase assignments)
                  </span>
                </span>
              </label>
            )}

            {!(mode === 'OPTIMISE' && useMeasured) && (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '12px 0 6px' }}>
                  <span style={fieldLabel}>Movement volumes</span>
                  <button
                    onClick={() => setMovements(prev => [...prev, emptyMovement(
                      Math.max(0, ...prev.map(m => m.phase_number)) + 2)])}
                    className="its-btn"
                    style={{ padding: '2px 8px' }}
                  >
                    <Plus size={11} />
                    <span>Add</span>
                  </button>
                </div>

                <div className="its-table-container">
                  <table className="its-table">
                    <thead>
                      <tr>
                        <th style={{ width: '70px' }}>Phase</th>
                        <th>Name</th>
                        <th style={{ width: '110px' }}>Volume (veh/h)</th>
                        <th style={{ width: '80px' }}>Lanes</th>
                        <th style={{ width: '40px' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {movements.map((movement, index) => (
                        <tr key={index}>
                          <td>
                            <input
                              type="number"
                              className="its-input"
                              value={movement.phase_number}
                              onChange={e => setMovements(prev => prev.map((m, i) =>
                                i === index ? { ...m, phase_number: Number(e.target.value) } : m))}
                              aria-label={`Phase number for row ${index + 1}`}
                            />
                          </td>
                          <td>
                            <input
                              className="its-input"
                              value={movement.name}
                              onChange={e => setMovements(prev => prev.map((m, i) =>
                                i === index ? { ...m, name: e.target.value } : m))}
                              aria-label={`Movement name for row ${index + 1}`}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              className="its-input"
                              value={movement.volume_vph}
                              placeholder="not entered"
                              onChange={e => setMovements(prev => prev.map((m, i) =>
                                i === index ? { ...m, volume_vph: e.target.value } : m))}
                              aria-label={`Volume for row ${index + 1}`}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              className="its-input"
                              value={movement.lanes}
                              min={1}
                              onChange={e => setMovements(prev => prev.map((m, i) =>
                                i === index ? { ...m, lanes: Number(e.target.value) } : m))}
                              aria-label={`Lanes for row ${index + 1}`}
                            />
                          </td>
                          <td>
                            <button
                              onClick={() => setMovements(prev => prev.filter((_, i) => i !== index))}
                              className="its-btn"
                              style={{ padding: '2px 6px' }}
                              aria-label={`Remove row ${index + 1}`}
                            >
                              <Trash2 size={11} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px', lineHeight: 1.5 }}>
                  Minimum and maximum green come from the real controller configuration.
                  Volumes are never generated — a blank row is simply not included.
                </div>
              </>
            )}

            {mode === 'SCENARIO' && (
              <>
                <label style={fieldLabel} htmlFor="scn-label">Scenario label</label>
                <input id="scn-label" className="its-input" value={label} onChange={e => setLabel(e.target.value)} />
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px', fontSize: 'var(--text-2xs)' }}>
                  <input
                    type="checkbox"
                    checked={compareToMeasured}
                    onChange={e => setCompareToMeasured(e.target.checked)}
                    style={{ accentColor: 'var(--its-text-accent)' }}
                  />
                  <span>Compare against measured conditions (refused if too few samples)</span>
                </label>
              </>
            )}

            <button
              onClick={mode === 'OPTIMISE' ? runOptimiser : runScenario}
              className="its-btn its-btn-primary"
              disabled={busy || !intersectionId}
              style={{ justifyContent: 'center', width: '100%', marginTop: '12px' }}
            >
              {mode === 'OPTIMISE' ? <Calculator size={13} /> : <Beaker size={13} />}
              <span>{busy ? 'Computing…' : mode === 'OPTIMISE' ? 'Compute recommendation' : 'Run scenario'}</span>
            </button>
          </>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="its-card"
          style={{ borderColor: 'var(--its-signal-red-border)', background: 'var(--its-signal-red-bg)' }}
        >
          <strong>REQUEST FAILED</strong>
          <div style={{ fontSize: 'var(--text-2xs)', marginTop: '4px' }}>{error}</div>
        </div>
      )}

      {/* Result ----------------------------------------------------------- */}
      {active && (
        <div
          className="its-card"
          style={
            mode === 'SCENARIO'
              ? {
                  // A scenario is banded so it can never be mistaken at a glance
                  // for an observed or actionable result.
                  borderColor: 'var(--its-text-indigo)',
                  borderWidth: '2px',
                  borderStyle: 'dashed',
                }
              : undefined
          }
        >
          {mode === 'SCENARIO' && (
            <div
              style={{
                margin: '-16px -16px 12px', padding: '8px 16px',
                background: 'var(--its-text-indigo)', color: '#ffffff',
                fontFamily: 'var(--font-mono)', fontSize: 'var(--text-2xs)',
                fontWeight: 700, letterSpacing: '0.08em',
                borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
              }}
            >
              {active.result_type} — NOT OBSERVED DATA
            </div>
          )}

          <div className="its-card-header">
            <span className="its-card-title">
              {mode === 'OPTIMISE' ? 'Recommendation' : active.label}
            </span>
            <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              {active.method_version ?? 'webster_hcm_v1'}
            </span>
          </div>

          {active.status === 'REFUSED' ? (
            <div
              style={{
                padding: '12px 14px', borderRadius: 'var(--radius-md)',
                border: '1px solid var(--its-signal-yellow-border)',
                background: 'var(--its-signal-yellow-bg)',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)' }}>
                REFUSED — {active.reason ?? active.refusal_reason}
              </div>
              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '6px', lineHeight: 1.6 }}>
                {(active.trace ?? active.calculation_trace ?? []).slice(-1)[0]?.source ??
                  active.detail ??
                  'The method cannot produce a defensible answer from these inputs, so it produced none.'}
              </div>
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', marginBottom: '6px' }}>
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                    Cycle length
                  </div>
                  <div className="mono" style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>
                    {active.cycle_length_sec ?? active.scenario_cycle_length_sec}s
                  </div>
                </div>

                {(active.expected_delay ?? active.scenario_expected_delay) && (
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                      Estimated delay
                    </div>
                    <div className="mono" style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>
                      {(active.expected_delay ?? active.scenario_expected_delay)
                        .volume_weighted_delay_sec_per_veh}s
                      <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}> /veh</span>
                    </div>
                  </div>
                )}
              </div>

              {(active.expected_delay ?? active.scenario_expected_delay)?.uncertainty && (
                <div
                  style={{
                    fontSize: '10px', color: 'var(--its-text-secondary)',
                    fontStyle: 'italic', lineHeight: 1.6, marginBottom: '8px',
                  }}
                >
                  {(active.expected_delay ?? active.scenario_expected_delay).uncertainty}
                </div>
              )}

              {/* Safety verdict: optimiser only. */}
              {mode === 'OPTIMISE' && active.safety_verdict && (
                <div
                  style={{
                    padding: '10px 12px', borderRadius: 'var(--radius-md)', marginBottom: '10px',
                    border: `1px solid ${active.safety_passed ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'}`,
                    background: active.safety_passed ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '7px', fontWeight: 700, fontSize: 'var(--text-xs)' }}>
                    {active.safety_passed
                      ? <ShieldCheck size={14} color="var(--its-signal-green)" />
                      : <ShieldX size={14} color="var(--its-signal-red)" />}
                    <span>
                      SAFETY ENGINE: {active.safety_passed ? 'PROPOSAL PASSES' : 'PROPOSAL REJECTED'}
                    </span>
                  </div>
                  {(active.safety_verdict.violations ?? []).length > 0 && (
                    <ul style={{ margin: '6px 0 0', paddingLeft: '18px', fontSize: 'var(--text-2xs)', lineHeight: 1.6 }}>
                      {active.safety_verdict.violations.map((v: string, i: number) => (
                        <li key={i}>{v}</li>
                      ))}
                    </ul>
                  )}
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px' }}>
                    {active.actionable_note}
                  </div>
                </div>
              )}

              {/* Scenario baseline comparison */}
              {mode === 'SCENARIO' && active.measured_baseline && (
                <div
                  style={{
                    padding: '10px 12px', borderRadius: 'var(--radius-sm)',
                    background: 'var(--its-bg-subsurface)', marginBottom: '10px',
                    fontSize: 'var(--text-2xs)', lineHeight: 1.6,
                  }}
                >
                  <div style={{ fontWeight: 700, marginBottom: '4px' }}>
                    BASELINE: {active.measured_baseline.status}
                  </div>
                  {active.measured_baseline.explanation}
                  {active.comparison && (
                    <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <TrendingDown
                        size={13}
                        color={active.comparison.direction === 'IMPROVEMENT'
                          ? 'var(--its-signal-green)' : 'var(--its-signal-yellow)'}
                      />
                      <span className="mono" style={{ fontWeight: 700 }}>
                        {active.comparison.change_sec_per_veh > 0 ? '+' : ''}
                        {active.comparison.change_sec_per_veh}s/veh ({active.comparison.direction})
                      </span>
                    </div>
                  )}
                  {active.comparison?.caveat && (
                    <div style={{ marginTop: '6px', color: 'var(--its-text-muted)', fontStyle: 'italic' }}>
                      {active.comparison.caveat}
                    </div>
                  )}
                </div>
              )}

              <SplitsTable splits={active.splits ?? active.scenario_splits ?? []} />

              <details style={{ marginTop: '12px' }}>
                <summary style={{ cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: 700 }}>
                  Calculation trace ({(active.trace ?? active.calculation_trace ?? []).length} steps)
                </summary>
                <TraceTable trace={active.trace ?? active.calculation_trace ?? []} />
              </details>

              {mode === 'SCENARIO' && (
                <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px', lineHeight: 1.6 }}>
                  {active.disclaimer}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Scenario history -------------------------------------------------- */}
      {mode === 'SCENARIO' && history.length > 0 && (
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              <FlaskConical size={14} color="var(--its-text-indigo)" />
              <span>Previous scenarios</span>
            </span>
            <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              STORED SEPARATELY FROM OBSERVED DATA
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {history.map(run => (
              <div
                key={run.scenario_id}
                style={{
                  display: 'flex', justifyContent: 'space-between', gap: '12px',
                  padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--its-bg-subsurface)', fontSize: 'var(--text-2xs)',
                }}
              >
                <span style={{ fontWeight: 600 }}>{run.label}</span>
                <span className="mono" style={{ color: 'var(--its-text-muted)' }}>
                  {run.status === 'COMPUTED' ? `${run.scenario_cycle_length_sec}s cycle` : run.refusal_reason}
                  {' · '}{formatTimestamp(run.created_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const fieldLabel: React.CSSProperties = {
  display: 'block',
  fontSize: 'var(--text-2xs)',
  color: 'var(--its-text-muted)',
  textTransform: 'uppercase',
  fontWeight: 600,
  letterSpacing: '0.05em',
  marginTop: '4px',
};
