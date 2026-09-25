import React from 'react';
import { CheckCircle2, Clock, Route, ShieldAlert, XCircle } from 'lucide-react';

/**
 * TRAFFICINTEL AI - Green-Wave Plan Panel
 *
 * Renders a coordination plan exactly as the backend stored it: what was
 * proposed, what the Safety Engine said about each controller, and - once
 * applied - what each controller acknowledged and read back.
 *
 * What the layout keeps apart, because confusing them is how a plan gets
 * trusted too far:
 *
 *   PLANNED    offsets and greens computed from design speed and demand. The
 *              diagram here is labelled PLANNED and drawn in outline.
 *   APPLIED    per-controller outcome of the write, with read-back. A plan that
 *              applied on some controllers and not others says so by name.
 *   OBSERVED   whether the controllers are actually running it comes only from
 *              `verify`, which compares against the stringline. This panel
 *              never claims the wave is working.
 */

export interface CoordinationPlan {
  plan_id?: string;
  status: string;
  reason?: string;
  detail?: string;
  corridor_name?: string;
  direction?: string;
  design_speed_kph?: number;
  speed_basis?: string;
  cycle_sec?: number;
  cycle_basis?: string;
  coord_phase?: number;
  junction_plans?: any[];
  bandwidth?: any;
  safety?: any;
  uncoordinated?: any[];
  apply_results?: any;
  applied_by?: string | null;
  applied_at?: string | null;
  time_reference_note?: string;
  minimum_feasible_cycle_sec?: number;
}

const STATUS_LOOK: Record<string, { color: string; label: string }> = {
  PROPOSED: { color: 'var(--its-text-accent)', label: 'PROPOSED - NOT YET APPLIED' },
  APPLIED: { color: 'var(--its-signal-green)', label: 'APPLIED TO EVERY CONTROLLER' },
  PARTIALLY_APPLIED: { color: 'var(--its-signal-yellow)', label: 'PARTIALLY APPLIED' },
  APPLY_FAILED: { color: 'var(--its-signal-red)', label: 'APPLY FAILED - NO CONTROLLER ACCEPTED IT' },
  REJECTED_BY_SAFETY: { color: 'var(--its-signal-red)', label: 'REJECTED BY SAFETY ENGINE' },
  REJECTED_AT_APPLY: { color: 'var(--its-signal-red)', label: 'REJECTED AT APPLY - NOTHING WAS SENT' },
};

const W = 620;
const ROW = 26;
const PAD_LEFT = 150;

const PlannedDiagram: React.FC<{ plans: any[]; cycle: number }> = ({ plans, cycle }) => {
  const width = W - PAD_LEFT - 10;
  const height = plans.length * ROW + 34;
  const x = (seconds: number) => PAD_LEFT + (seconds / cycle) * width;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${height}`}
      role="img"
      aria-label="Planned coordinated green windows by junction over one cycle"
      style={{ display: 'block', maxWidth: `${W}px` }}
    >
      <text x={PAD_LEFT} y={11} fontSize="9" fill="var(--its-text-muted)" letterSpacing="0.06em">
        PLANNED COORDINATED GREEN - ONE {cycle}s CYCLE (NOT OBSERVED)
      </text>
      {plans.map((plan, index) => {
        const y = 18 + index * ROW;
        const start = plan.offset_sec % cycle;
        const end = start + plan.coordinated_green_sec;
        const segments = end <= cycle ? [[start, end]] : [[start, cycle], [0, end - cycle]];
        return (
          <g key={plan.intersection_id}>
            <text x={PAD_LEFT - 8} y={y + 14} textAnchor="end" fontSize="10" fill="var(--its-text-primary)">
              {plan.name.length > 22 ? `${plan.name.slice(0, 21)}...` : plan.name}
            </text>
            <rect x={PAD_LEFT} y={y + 3} width={width} height={ROW - 8}
                  fill="none" stroke="var(--its-border-subtle)" />
            {segments.map(([a, b], i) => (
              <rect key={i} x={x(a)} y={y + 3} width={Math.max(x(b) - x(a), 1)} height={ROW - 8}
                    fill="var(--its-signal-green)" fillOpacity="0.18"
                    stroke="var(--its-signal-green)" strokeDasharray="4 2" data-kind="PLANNED" />
            ))}
            <text x={x(start) + 3} y={y + 16} fontSize="9" fill="var(--its-text-secondary)" className="mono">
              +{plan.offset_sec}s
            </text>
          </g>
        );
      })}
    </svg>
  );
};

export const CoordinationPlanPanel: React.FC<{ plan: CoordinationPlan }> = ({ plan }) => {
  // Refusals come back without a stored plan.
  if (plan.status === 'NOT_COMPUTABLE' || plan.status === 'REFUSED') {
    return (
      <div className="its-panel" style={{ padding: '16px' }}>
        <div style={{ fontSize: '12px', fontWeight: 800, color: 'var(--its-text-muted)', letterSpacing: '0.05em' }}>
          {plan.status.replace(/_/g, ' ')}
        </div>
        {plan.reason && (
          <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
            {plan.reason}
          </div>
        )}
        <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '6px', lineHeight: 1.6 }}>
          {plan.detail}
        </div>
        {(plan.uncoordinated?.length ?? 0) > 0 && (
          <div className="its-table-container" style={{ marginTop: '10px' }}>
            <table className="its-table">
              <thead><tr><th>Junction</th><th>Why it cannot be coordinated</th></tr></thead>
              <tbody>
                {plan.uncoordinated!.map((u) => (
                  <tr key={u.intersection_id}>
                    <td>{u.name}</td>
                    <td className="mono" style={{ fontSize: '10px' }}>{u.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  const look = STATUS_LOOK[plan.status] || { color: 'var(--its-text-muted)', label: plan.status };
  const plans = plan.junction_plans || [];
  const band = plan.bandwidth || {};
  const safety = plan.safety?.per_junction || [];
  const dispatched = plan.apply_results?.dispatched || [];
  const preflight = plan.apply_results?.preflight || [];

  return (
    <div className="its-panel">
      <div style={{ padding: '14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
        <div style={{ fontSize: '13px', fontWeight: 800, color: look.color, letterSpacing: '0.04em' }}>
          {look.label}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '18px', marginTop: '8px', fontSize: '11px' }} className="mono">
          <span>
            <Clock size={11} style={{ verticalAlign: '-1px' }} /> CYCLE {plan.cycle_sec}s
            <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}> {plan.cycle_basis}</span>
          </span>
          <span>
            <Route size={11} style={{ verticalAlign: '-1px' }} /> DESIGN SPEED {plan.design_speed_kph} km/h
            <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}> {plan.speed_basis?.replace(/_/g, ' ')} - NOT MEASURED</span>
          </span>
          <span>{plan.direction} · coordinated phase {plan.coord_phase}</span>
        </div>
      </div>

      {plans.length > 0 && plan.cycle_sec && (
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
          <PlannedDiagram plans={plans} cycle={plan.cycle_sec} />
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '22px', padding: '10px 14px', borderBottom: '1px solid var(--its-border-subtle)', fontSize: '11px' }} className="mono">
        <span>
          <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>DESIGN-DIRECTION BAND </span>
          {band.design_direction_sec}s ({Math.round((band.design_direction_efficiency || 0) * 100)}%)
        </span>
        <span>
          <span style={{ color: 'var(--its-text-muted)', fontSize: '9px' }}>OPPOSITE-DIRECTION BAND </span>
          {band.opposite_direction_sec}s ({Math.round((band.opposite_direction_efficiency || 0) * 100)}%)
        </span>
        {band.basis && (
          <span style={{ flexBasis: '100%', fontSize: '9px', color: 'var(--its-text-muted)', fontFamily: 'inherit' }}>
            {band.basis}
          </span>
        )}
      </div>

      <div className="its-table-container">
        <table className="its-table">
          <thead>
            <tr>
              <th>Junction</th>
              <th>Position</th>
              <th>Offset</th>
              <th>Splits (2/4/6/8)</th>
              <th>Webster / feasible</th>
              <th>Safety Engine</th>
              {dispatched.length > 0 && <th>Applied</th>}
            </tr>
          </thead>
          <tbody>
            {plans.map((j) => {
              const verdict = safety.find((s: any) => s.intersection_id === j.intersection_id);
              const outcome = dispatched.find((d: any) => d.intersection_id === j.intersection_id);
              return (
                <tr key={j.intersection_id}>
                  <td style={{ fontWeight: 600 }}>{j.name}</td>
                  <td className="mono">{j.position_m} m</td>
                  <td className="mono">
                    {j.offset_sec}s
                    <div style={{ fontSize: '9px', color: 'var(--its-text-muted)' }}>travel {j.travel_time_from_origin_sec}s</div>
                  </td>
                  <td className="mono" style={{ fontSize: '10px' }}>
                    {['2', '4', '6', '8'].map((p) => j.splits?.[p] ?? '-').join(' / ')}
                  </td>
                  <td className="mono" style={{ fontSize: '10px' }}>
                    {j.own_optimum_cycle_sec}s / {j.minimum_feasible_cycle_sec ?? '-'}s
                  </td>
                  <td style={{ fontSize: '10px' }}>
                    {verdict?.is_safe ? (
                      <span style={{ color: 'var(--its-signal-green)' }}><CheckCircle2 size={11} /> PASSED</span>
                    ) : (
                      <span style={{ color: 'var(--its-signal-red)' }}>
                        <XCircle size={11} /> REJECTED
                        <div style={{ color: 'var(--its-text-muted)' }}>{verdict?.violations?.[0]}</div>
                      </span>
                    )}
                  </td>
                  {dispatched.length > 0 && (
                    <td style={{ fontSize: '10px' }} className="mono">
                      {outcome ? outcome.status : 'NOT SENT'}
                      {outcome && (
                        <div style={{ color: outcome.readback_matches ? 'var(--its-signal-green)' : 'var(--its-signal-red)' }}>
                          {outcome.readback_matches ? 'read-back matches' : 'read-back differs'}
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {plan.status === 'REJECTED_AT_APPLY' && preflight.length > 0 && (
        <div style={{ padding: '10px 14px', fontSize: '10px', lineHeight: 1.6, borderTop: '1px solid var(--its-border-subtle)' }}>
          <ShieldAlert size={12} style={{ verticalAlign: '-2px', color: 'var(--its-signal-red)' }} />{' '}
          Re-validation at apply time failed for:{' '}
          {preflight.filter((p: any) => !p.is_safe).map((p: any) => `${p.name} (${p.violations[0]})`).join('; ')}.
          Nothing was sent to any controller: a half-applied green wave moves junctions off their old timing
          without the progression that justified it.
        </div>
      )}

      {(plan.uncoordinated?.length ?? 0) > 0 && (
        <div style={{ padding: '10px 14px', fontSize: '10px', lineHeight: 1.6, borderTop: '1px solid var(--its-border-subtle)', background: 'var(--its-bg-elevated)' }}>
          <strong>NOT COORDINATED: </strong>
          {plan.uncoordinated!.map((u) => `${u.name} (${u.reason})`).join('; ')}. Progression through these
          junctions is not controlled by this plan.
        </div>
      )}

      {plan.time_reference_note && (
        <div style={{ padding: '10px 14px', fontSize: '9px', color: 'var(--its-text-muted)', lineHeight: 1.6, borderTop: '1px solid var(--its-border-subtle)' }}>
          {plan.time_reference_note}
        </div>
      )}
    </div>
  );
};

export const CoordinationVerifyPanel: React.FC<{ result: any }> = ({ result }) => {
  const color =
    result.status === 'OBSERVED_AS_PLANNED' ? 'var(--its-signal-green)'
      : result.status === 'DIVERGES_FROM_PLAN' ? 'var(--its-signal-red)'
        : 'var(--its-text-muted)';
  return (
    <div className="its-panel">
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
        <div style={{ fontSize: '12px', fontWeight: 800, color, letterSpacing: '0.04em' }}>
          {result.status.replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
          {result.detail}
        </div>
      </div>
      {result.segments?.length > 0 && (
        <div className="its-table-container">
          <table className="its-table">
            <thead>
              <tr><th>Segment</th><th>Planned offset</th><th>Observed offset</th><th>Difference</th><th>Result</th></tr>
            </thead>
            <tbody>
              {result.segments.map((s: any, i: number) => (
                <tr key={i}>
                  <td style={{ fontSize: '10px' }}>{s.from} → {s.to}</td>
                  <td className="mono">{`${s.planned_offset_sec}s`}</td>
                  <td className="mono">
                    {s.observed_median_offset_sec != null ? `${s.observed_median_offset_sec}s` : '--'}
                  </td>
                  <td className="mono">
                    {s.difference_sec != null ? `${s.difference_sec}s (tol ${s.tolerance_sec}s)` : '--'}
                  </td>
                  <td style={{ fontSize: '10px' }}>{s.status.replace(/_/g, ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ padding: '8px 14px', fontSize: '9px', color: 'var(--its-text-muted)' }}>{result.basis}</div>
    </div>
  );
};
