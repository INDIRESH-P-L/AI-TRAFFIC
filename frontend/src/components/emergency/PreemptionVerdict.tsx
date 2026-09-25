import React from 'react';

/**
 * TRAFFICINTEL AI - Preemption Verdict
 *
 * The result of one preemption request, stated as what happened at the
 * controller. "Passed the Safety Engine" is not "granted": since preemption
 * calls are actually dispatched, a call can pass validation and still fail at
 * the controller, and that case is never rendered as success.
 *
 *   ACTIVE    controller acknowledged the hold
 *   FAILED    validated, but the controller did not acknowledge - no
 *             preemption is in effect
 *   REJECTED  the Safety Engine refused it; nothing was sent
 */
export const PreemptionVerdict: React.FC<{ verdict: any }> = ({ verdict }) => (
    <div
      role="status"
      aria-live="polite"
      style={{
        marginTop: '14px',
        padding: '12px 14px',
        borderRadius: 'var(--radius-md)',
        border: `1px solid ${
          verdict.status === 'ACTIVE'
            ? 'var(--its-signal-green-border)'
            : verdict.status === 'FAILED'
              ? 'var(--its-signal-yellow-border)'
              : 'var(--its-signal-red-border)'
        }`,
        background: verdict.status === 'ACTIVE'
          ? 'var(--its-signal-green-bg)'
          : verdict.status === 'FAILED'
            ? 'var(--its-signal-yellow-bg)'
            : 'var(--its-signal-red-bg)',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          color: 'var(--its-text-primary)',
          marginBottom: verdict.safety_clearance_passed ? 0 : '8px',
        }}
      >
        {verdict.status === 'ERROR'
          ? `REQUEST FAILED: ${verdict.error}`
          : verdict.status === 'ACTIVE'
            ? `PREEMPTION ACTIVE — CONTROLLER ACKNOWLEDGED (phase ${verdict.requested_phase})`
            : verdict.status === 'FAILED'
              ? 'SAFETY ENGINE PASSED, BUT THE CONTROLLER DID NOT ACKNOWLEDGE — NO PREEMPTION IS IN EFFECT'
              : 'PREEMPTION REJECTED BY SAFETY ENGINE — NOTHING WAS SENT'}
      </div>

      {!verdict.safety_clearance_passed && verdict.safety_report?.violations?.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: '18px', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', lineHeight: 1.6 }}>
          {verdict.safety_report.violations.map((violation: string, i: number) => (
            <li key={i}>{violation}</li>
          ))}
        </ul>
      )}

      {verdict.safety_report?.checks_performed?.length > 0 && (
        <div style={{ marginTop: '8px', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--its-text-muted)' }}>
          CHECKS RUN: {verdict.safety_report.checks_performed.join(' • ')}
        </div>
      )}
    </div>
);
