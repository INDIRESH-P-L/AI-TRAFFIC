import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle, ArrowRight, Check, CheckCircle2, FileText, Loader2,
  ShieldCheck, ShieldX, X,
} from 'lucide-react';
import { api } from '../api/client';
import { clientId } from '../lib/entropy';
import { formatTimestamp } from '../lib/quality';
import { Skeleton } from './Skeleton';

/**
 * TRAFFICINTEL AI - Guided signal command workflow
 *
 * Four steps: PROPOSE -> VALIDATE -> CONFIRM -> RESULT.
 *
 * The validate step calls the same Deterministic Safety Engine the execute
 * step calls; it is a dry run of the real path, not a client-side lookalike.
 * Each rule renders as its own row with a pass/fail mark and a plain-language
 * explanation, so an operator reads "phase 4 conflicts with the phase showing
 * green" rather than a rejection code.
 *
 * On success the result reports what the CONTROLLER did, which is a different
 * claim from what was requested: a hold accepted for a phase that is not
 * currently green is reported as accepted-not-yet-displaying, never as done.
 */

type Step = 'PROPOSE' | 'VALIDATE' | 'CONFIRM' | 'RESULT';

interface SafetyCheck {
  code: string;
  label: string;
  passed: boolean;
  detail: string;
  standard?: string | null;
}

interface Props {
  controllers: any[];
  preselectedControllerId?: string | null;
  onClose: () => void;
  onExecuted?: (result: any) => void;
}

const SafetyCheckRow: React.FC<{ check: SafetyCheck }> = ({ check }) => (
  <div className={`safety-check-row ${check.passed ? 'passed' : 'failed'}`}>
    <span
      style={{ color: check.passed ? 'var(--its-signal-green)' : 'var(--its-signal-red)', marginTop: '1px' }}
      aria-hidden="true"
    >
      {check.passed ? <CheckCircle2 size={15} /> : <ShieldX size={15} />}
    </span>

    <div style={{ flex: 1, minWidth: 0 }}>
      <div
        style={{
          fontSize: 'var(--text-xs)', fontWeight: 700,
          color: 'var(--its-text-primary)', display: 'flex',
          alignItems: 'center', gap: '8px', flexWrap: 'wrap',
        }}
      >
        <span>{check.label}</span>
        <span
          className="mono"
          style={{
            fontSize: '9px', color: check.passed ? 'var(--its-signal-green)' : 'var(--its-signal-red)',
            border: '1px solid currentColor', borderRadius: 'var(--radius-xs)', padding: '0 4px',
          }}
        >
          {check.passed ? 'PASS' : 'FAIL'}
        </span>
      </div>

      <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '3px', lineHeight: 1.5 }}>
        {check.detail}
      </div>

      {check.standard && (
        <div className="mono" style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
          {check.standard}
        </div>
      )}
    </div>
  </div>
);

export const SignalCommandWorkflow: React.FC<Props> = ({
  controllers,
  preselectedControllerId,
  onClose,
  onExecuted,
}) => {
  const [step, setStep] = useState<Step>('PROPOSE');
  const [controllerId, setControllerId] = useState<string>(
    preselectedControllerId || controllers[0]?.id || '',
  );
  const [phase, setPhase] = useState<number>(2);
  const [duration, setDuration] = useState<number>(15);

  const [idempotencyKey, setIdempotencyKey] = useState(() => clientId('cmd'));
  const [preview, setPreview] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const controller = controllers.find(c => c.id === controllerId);
  const phases: any[] = controller?.phases ?? [];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const runValidation = useCallback(async () => {
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      const response = await api.validateSignalCommand({
        controller_id: controllerId,
        requested_phase: phase,
        command_type: 'PHASE_HOLD',
        duration_sec: duration,
        idempotency_key: idempotencyKey,
      });
      setPreview(response);
      setStep('VALIDATE');
    } catch (err: any) {
      setError(err.message || 'Validation request failed');
      setStep('VALIDATE');
    } finally {
      setBusy(false);
    }
  }, [controllerId, phase, duration, idempotencyKey]);

  const execute = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.issueSignalCommand({
        controller_id: controllerId,
        requested_phase: phase,
        command_type: 'PHASE_HOLD',
        duration_sec: duration,
        idempotency_key: idempotencyKey,
      });
      setResult(response);
      setStep('RESULT');
      onExecuted?.(response);
    } catch (err: any) {
      setError(err.message || 'Command request failed');
      setStep('RESULT');
    } finally {
      setBusy(false);
    }
  }, [controllerId, phase, duration, idempotencyKey, onExecuted]);

  const restart = () => {
    // A fresh key: the previous one is spent, and reusing it would be rejected
    // by the idempotency check rather than issuing a new command.
    setIdempotencyKey(clientId('cmd'));
    setPreview(null);
    setResult(null);
    setError(null);
    setStep('PROPOSE');
  };

  const checks: SafetyCheck[] = preview?.safety_report?.checks ?? [];
  const accepted = preview?.would_be_accepted === true;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside
        className="junction-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Signal command workflow"
      >
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={17} color="var(--its-text-accent)" />
            <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, letterSpacing: '0.04em' }}>
              SIGNAL COMMAND
            </span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close command workflow"
            style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--its-text-muted)' }}
          >
            <X size={17} />
          </button>
        </div>

        {/* Stepper --------------------------------------------------------- */}
        <div
          style={{
            display: 'flex', gap: '6px', padding: '10px 16px',
            borderBottom: '1px solid var(--its-border-subtle)',
          }}
        >
          {(['PROPOSE', 'VALIDATE', 'CONFIRM', 'RESULT'] as Step[]).map((s, i) => {
            const order: Step[] = ['PROPOSE', 'VALIDATE', 'CONFIRM', 'RESULT'];
            const active = order.indexOf(step) >= i;
            return (
              <div key={s} style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1 }}>
                <span
                  className="mono"
                  style={{
                    fontSize: '9px', fontWeight: 700, padding: '2px 6px',
                    borderRadius: 'var(--radius-full)',
                    background: active ? 'var(--its-fresh-bg)' : 'var(--its-stale-bg)',
                    color: active ? 'var(--its-text-accent)' : 'var(--its-text-muted)',
                    border: `1px solid ${active ? 'var(--its-border-accent)' : 'var(--its-border-subtle)'}`,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {i + 1}. {s}
                </span>
                {i < 3 && <div style={{ flex: 1, height: 1, background: 'var(--its-border-subtle)' }} />}
              </div>
            );
          })}
        </div>

        <div className="junction-drawer-body">
          {/* ---- PROPOSE ---- */}
          {step === 'PROPOSE' && (
            <>
              {controllers.length === 0 ? (
                <div style={emptyBlock}>
                  <AlertTriangle size={24} color="var(--its-text-muted)" />
                  <div style={{ fontWeight: 700, marginTop: 8 }}>SIGNAL CONTROLLER: NOT CONNECTED</div>
                  <div style={{ marginTop: 4 }}>
                    No signal controller is configured. Add one under Settings before
                    issuing commands.
                  </div>
                </div>
              ) : (
                <>
                  <label style={fieldLabel} htmlFor="cmd-controller">Controller</label>
                  <select
                    id="cmd-controller"
                    className="its-select"
                    value={controllerId}
                    onChange={e => setControllerId(e.target.value)}
                  >
                    {controllers.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name} — {c.connection_status} ({c.protocol})
                      </option>
                    ))}
                  </select>

                  {controller && controller.connection_status !== 'CONNECTED' && (
                    <div style={warnBlock}>
                      This controller is <strong>{controller.connection_status}</strong>. The
                      Safety Engine refuses commands to hardware whose phase state cannot be
                      read; validation will show exactly why.
                    </div>
                  )}

                  <label style={fieldLabel} htmlFor="cmd-phase">Phase to hold</label>
                  <select
                    id="cmd-phase"
                    className="its-select"
                    value={phase}
                    onChange={e => setPhase(Number(e.target.value))}
                  >
                    {phases.length === 0 ? (
                      <option value={phase}>Phase {phase} (no phases configured)</option>
                    ) : (
                      phases.map((p: any) => (
                        <option key={p.phase_number} value={p.phase_number}>
                          Phase {p.phase_number} — {p.name} (ring {p.ring}, min {p.min_green}s, max {p.max_green}s)
                        </option>
                      ))
                    )}
                  </select>

                  <label style={fieldLabel} htmlFor="cmd-duration">Hold duration (seconds)</label>
                  <input
                    id="cmd-duration"
                    type="number"
                    className="its-input"
                    min={5}
                    max={120}
                    value={duration}
                    onChange={e => setDuration(Number(e.target.value))}
                  />
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
                    IDEMPOTENCY KEY: {idempotencyKey}
                  </div>

                  <button
                    onClick={runValidation}
                    className="its-btn its-btn-primary"
                    disabled={busy || !controllerId}
                    style={{ justifyContent: 'center', marginTop: '6px' }}
                  >
                    {busy ? <Loader2 size={13} className="pulse-indicator" /> : <ShieldCheck size={13} />}
                    <span>{busy ? 'Validating…' : 'Validate against Safety Engine'}</span>
                  </button>
                </>
              )}
            </>
          )}

          {/* ---- VALIDATE ---- */}
          {step === 'VALIDATE' && (
            <>
              {busy && (
                <>
                  <Skeleton height={44} />
                  <Skeleton height={44} />
                  <Skeleton height={44} />
                </>
              )}

              {!busy && error && (
                <div style={errorBlock} role="alert">
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>VALIDATION REQUEST FAILED</div>
                  <div>{error}</div>
                  <div style={{ marginTop: 8, color: 'var(--its-text-muted)' }}>
                    No command was sent. The controller was not contacted for execution.
                  </div>
                </div>
              )}

              {!busy && !error && preview && (
                <>
                  <div
                    style={{
                      padding: '10px 12px', borderRadius: 'var(--radius-md)',
                      border: `1px solid ${accepted ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'}`,
                      background: accepted ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
                    }}
                    role="status"
                  >
                    <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
                      {accepted
                        ? 'SAFETY ENGINE WOULD ACCEPT THIS COMMAND'
                        : 'SAFETY ENGINE WOULD REJECT THIS COMMAND'}
                    </div>
                    <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '3px' }}>
                      {checks.filter(c => c.passed).length} of {checks.length} rules pass.
                      Nothing has been sent to the controller.
                    </div>
                  </div>

                  {/* Live controller state the verdict was computed against. */}
                  {preview.controller_state && (
                    <div style={infoBlock}>
                      <div style={{ fontWeight: 700, marginBottom: '5px' }}>STATE USED FOR THIS VERDICT</div>
                      <div>Connection: <span className="mono">{preview.controller_state.connection_status}</span></div>
                      <div>
                        Green now:{' '}
                        <span className="mono">
                          {preview.controller_state.green_phases?.join(', ') || 'NONE READ'}
                        </span>
                      </div>
                      <div>
                        Clearing:{' '}
                        <span className="mono">
                          {preview.controller_state.clearing_phases?.join(', ') || 'NONE'}
                        </span>
                      </div>
                      <div>Read at: <span className="mono">{formatTimestamp(preview.controller_state.read_at)}</span></div>
                    </div>
                  )}

                  {checks.map(check => (
                    <SafetyCheckRow key={check.code} check={check} />
                  ))}

                  <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                    <button onClick={restart} className="its-btn" style={{ flex: 1, justifyContent: 'center' }}>
                      <span>Change request</span>
                    </button>
                    <button
                      onClick={() => setStep('CONFIRM')}
                      className="its-btn its-btn-primary"
                      disabled={!accepted}
                      title={accepted ? 'Continue to confirmation' : 'Cannot continue while a rule fails'}
                      style={{ flex: 1, justifyContent: 'center' }}
                    >
                      <span>Continue</span>
                      <ArrowRight size={13} />
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {/* ---- CONFIRM ---- */}
          {step === 'CONFIRM' && (
            <>
              <div style={warnBlock}>
                <div style={{ fontWeight: 700, marginBottom: '5px' }}>CONFIRM PHYSICAL SIGNAL CHANGE</div>
                This sends a hold to real traffic signal hardware at{' '}
                <strong>{controller?.name}</strong>. The Safety Engine will validate it
                again at execution time against the controller state as it is then — a
                preview is not a reservation.
              </div>

              <div style={infoBlock}>
                <div>Controller: <span className="mono">{controller?.name}</span></div>
                <div>Phase: <span className="mono">{phase}</span></div>
                <div>Duration: <span className="mono">{duration}s</span></div>
                <div>Key: <span className="mono">{idempotencyKey}</span></div>
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setStep('VALIDATE')} className="its-btn" style={{ flex: 1, justifyContent: 'center' }}>
                  <span>Back</span>
                </button>
                <button
                  onClick={execute}
                  className="its-btn its-btn-danger"
                  disabled={busy}
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  {busy ? <Loader2 size={13} className="pulse-indicator" /> : <Check size={13} />}
                  <span>{busy ? 'Sending…' : 'Send to controller'}</span>
                </button>
              </div>
            </>
          )}

          {/* ---- RESULT ---- */}
          {step === 'RESULT' && (
            <>
              {error && (
                <div style={errorBlock} role="alert">
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>COMMAND REQUEST FAILED</div>
                  <div>{error}</div>
                </div>
              )}

              {result && (
                <>
                  <div
                    style={{
                      padding: '10px 12px', borderRadius: 'var(--radius-md)',
                      border: `1px solid ${result.status === 'EXECUTED' ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'}`,
                      background: result.status === 'EXECUTED' ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
                    }}
                    role="status"
                  >
                    <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700 }}>
                      COMMAND {result.status}
                    </div>
                    <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '3px' }}>
                      Safety engine: {result.safety_check_passed ? 'PASSED' : 'REJECTED'}
                      {result.acknowledged_at && ` · acknowledged ${formatTimestamp(result.acknowledged_at)}`}
                    </div>
                  </div>

                  {/* What the hardware did, stated separately from what was asked. */}
                  {result.status === 'EXECUTED' && (
                    <div style={infoBlock}>
                      <div style={{ fontWeight: 700, marginBottom: '5px' }}>CONTROLLER EFFECT</div>
                      <div style={{ lineHeight: 1.6 }}>
                        The controller acknowledged the command. Whether the requested phase
                        is now displaying green is reported separately, from a read-back of
                        the hardware — see the junction timeline for the recorded verification.
                      </div>
                    </div>
                  )}

                  {!result.safety_check_passed && result.safety_report?.checks && (
                    <>
                      <div style={{ fontSize: 'var(--text-2xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}>
                        WHY IT WAS REJECTED
                      </div>
                      {(result.safety_report.checks as SafetyCheck[])
                        .filter(c => !c.passed)
                        .map(c => <SafetyCheckRow key={c.code} check={c} />)}
                    </>
                  )}

                  <div style={infoBlock}>
                    <FileText size={12} style={{ marginBottom: '-2px', marginRight: '5px' }} />
                    An immutable audit entry was written for this command, pass or fail.
                  </div>
                </>
              )}

              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={restart} className="its-btn" style={{ flex: 1, justifyContent: 'center' }}>
                  <span>New command</span>
                </button>
                <button onClick={onClose} className="its-btn its-btn-primary" style={{ flex: 1, justifyContent: 'center' }}>
                  <span>Done</span>
                </button>
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
};

const fieldLabel: React.CSSProperties = {
  display: 'block',
  fontSize: 'var(--text-2xs)',
  color: 'var(--its-text-muted)',
  textTransform: 'uppercase',
  fontWeight: 600,
  letterSpacing: '0.05em',
};

const infoBlock: React.CSSProperties = {
  padding: '10px 12px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--its-border-subtle)',
  background: 'var(--its-bg-subsurface)',
  fontSize: 'var(--text-2xs)',
  color: 'var(--its-text-secondary)',
  lineHeight: 1.7,
};

const warnBlock: React.CSSProperties = {
  ...infoBlock,
  border: '1px solid var(--its-signal-yellow-border)',
  background: 'var(--its-signal-yellow-bg)',
  color: 'var(--its-text-primary)',
};

const errorBlock: React.CSSProperties = {
  ...infoBlock,
  border: '1px solid var(--its-signal-red-border)',
  background: 'var(--its-signal-red-bg)',
  color: 'var(--its-text-primary)',
};

const emptyBlock: React.CSSProperties = {
  textAlign: 'center',
  padding: '36px 20px',
  color: 'var(--its-text-secondary)',
  fontSize: 'var(--text-xs)',
  lineHeight: 1.6,
};
