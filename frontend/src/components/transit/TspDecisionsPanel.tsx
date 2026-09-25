import React from 'react';
import { Bus } from 'lucide-react';

/**
 * TRAFFICINTEL AI - Conditional TSP Decisions
 *
 * One row per bus the feed contained, with the decision and its reason. The
 * buses that were NOT given priority matter as much as the ones that were: an
 * operator asked "why didn't route 12 get priority?" needs the answer
 * (unknown lateness, arrived on red, lockout) on screen, not inferred from a
 * missing row.
 */

const DECISION_COLOR: Record<string, string> = {
  GRANTED_GREEN_EXTENSION: 'var(--its-signal-green)',
  WOULD_REQUEST_GREEN_EXTENSION: 'var(--its-text-accent)',
  REJECTED_BY_SAFETY_ENGINE: 'var(--its-signal-red)',
  DISPATCH_FAILED: 'var(--its-signal-red)',
};

export const TspDecisionsPanel: React.FC<{ result: any }> = ({ result }) => {
  if (result.status !== 'EVALUATED') {
    return (
      <div className="its-panel" style={{ padding: '16px' }}>
        <div style={{ fontSize: '12px', fontWeight: 800, color: 'var(--its-text-muted)', letterSpacing: '0.05em' }}>
          {result.status.replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '6px', lineHeight: 1.6 }}>
          {result.detail}
        </div>
      </div>
    );
  }

  const decisions: any[] = result.decisions || [];
  const conditions = result.conditions || {};

  return (
    <div className="its-panel">
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--its-border-subtle)' }}>
        <div style={{ fontSize: '12px', fontWeight: 800, letterSpacing: '0.04em' }}>
          {result.dry_run ? 'DRY RUN - NOTHING SENT, NOTHING RECORDED' : 'EVALUATED AND DISPATCHED'}
        </div>
        <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}>
          {result.vehicles_in_feed} vehicle(s) · {result.trip_updates_in_feed} trip update(s)
          {!result.schedule_adherence_available && ' · NO SCHEDULE ADHERENCE IN FEED - lateness unknown, no priority possible'}
        </div>
      </div>

      {decisions.length === 0 ? (
        <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
          THE FEED CONTAINED NO VEHICLES. No bus is shown that the feed did not report.
        </div>
      ) : (
        <div className="its-table-container">
          <table className="its-table">
            <thead>
              <tr><th>Vehicle</th><th>Junction</th><th>Delay</th><th>Decision</th></tr>
            </thead>
            <tbody>
              {decisions.map((d, i) => (
                <tr key={`${d.vehicle_id}-${i}`}>
                  <td className="mono" style={{ fontSize: '10px' }}>
                    {d.vehicle_id}
                    <div style={{ color: 'var(--its-text-muted)' }}>route {d.route_id || '--'}</div>
                  </td>
                  <td style={{ fontSize: '10px' }}>
                    {d.target ? (
                      <>
                        {d.target.name}
                        <div style={{ color: 'var(--its-text-muted)' }}>
                          {d.target.distance_m} m · {d.target.approach?.toLowerCase()}
                        </div>
                      </>
                    ) : '--'}
                  </td>
                  <td className="mono" style={{ fontSize: '10px' }}>
                    {d.delay_sec == null ? 'UNKNOWN' : `${d.delay_sec > 0 ? '+' : ''}${d.delay_sec}s`}
                  </td>
                  <td style={{ fontSize: '10px' }}>
                    <div style={{ fontWeight: 700, color: DECISION_COLOR[d.decision] || 'var(--its-text-secondary)' }}>
                      {d.decision.replace(/_/g, ' ')}
                    </div>
                    <div style={{ color: 'var(--its-text-muted)', lineHeight: 1.5 }}>{d.detail}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ padding: '10px 14px', fontSize: '9px', color: 'var(--its-text-muted)', lineHeight: 1.6 }}>
        <Bus size={11} style={{ verticalAlign: '-2px' }} /> Conditional TSP: granted only to buses at least{' '}
        {conditions.min_lateness_sec}s late, within {conditions.detection_radius_m} m and heading toward the junction,
        on an approach whose phase is already green (green extension of {conditions.extension_sec}s), with a{' '}
        {conditions.lockout_sec}s recovery lockout per junction. Early green is not requested: it needs NTCIP
        force-off, which this adapter does not implement.
      </div>
    </div>
  );
};
