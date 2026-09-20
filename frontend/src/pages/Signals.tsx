import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { RingBarrierDiagram } from '../components/RingBarrierDiagram';
import { useAuth } from '../context/AuthContext';
import {
  Sliders,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  Play,
  X,
  ArrowRight,
  UserCheck
} from 'lucide-react';

export const Signals: React.FC = () => {
  const { user } = useAuth();
  const [controllers, setControllers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);

  // Command Modal State
  const [selectedCtrl, setSelectedCtrl] = useState<any | null>(null);
  const [targetPhase, setTargetPhase] = useState<number>(2);
  const [duration, setDuration] = useState<number>(15);
  const [issuing, setIssuing] = useState(false);
  const [commandReport, setCommandReport] = useState<any | null>(null);

  const loadControllers = useCallback(async () => {
    try {
      const data = await api.getControllers();
      setControllers(data);
    } catch (err) {
      console.error('Failed to load controllers', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadControllers();
  }, [loadControllers]);

  const handleTestConnection = async (id: string) => {
    setTestingId(id);
    try {
      const res = await api.testControllerConnection(id);
      await loadControllers();
      alert(`Hardware test result: ${res.connection_status}\n${res.health_details.message}`);
    } catch (err: any) {
      alert(`Connection test error: ${err.message}`);
    } finally {
      setTestingId(null);
    }
  };

  const handleIssueCommand = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCtrl) return;
    setIssuing(true);
    setCommandReport(null);

    const idempotencyKey = `cmd_${Date.now()}_${crypto.randomUUID()}`;

    try {
      const res = await api.issueSignalCommand({
        controller_id: selectedCtrl.id,
        requested_phase: targetPhase,
        command_type: 'PHASE_HOLD',
        duration_sec: duration,
        idempotency_key: idempotencyKey,
      });
      setCommandReport(res);
      await loadControllers();
    } catch (err: any) {
      alert(`Failed to issue command: ${err.message}`);
    } finally {
      setIssuing(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Header */}
      <div
        style={{
          background: 'var(--its-gradient-hero)',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-lg)',
          padding: '18px 22px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: 'var(--text-lg)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
              SIGNAL CONTROLLER & NEMA TS2 ENGINE
            </h1>
            <span className="status-badge active">NTCIP 1202</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '4px' }}>
            Deterministic dual-ring barrier conflict interlocks & field TCP socket reachability telemetry.
          </div>
        </div>

        <button
          onClick={loadControllers}
          className="its-btn"
          disabled={loading}
          title="Poll controller states"
        >
          <RefreshCw size={13} className={loading ? 'pulse-indicator' : ''} />
          <span>Sync Controllers</span>
        </button>
      </div>

      {controllers.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="NO SIGNAL CONTROLLERS CONFIGURED"
          description="No physical traffic signal controllers have been registered. Add an intersection controller to enable telemetry and deterministic safety-gated commands."
          actionText="Configure in Settings"
          actionLink="/settings"
          icon={<Sliders size={36} />}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {controllers.map((ctrl) => (
            <div key={ctrl.id} className="its-card">
              <div className="its-card-header">
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontWeight: 700, fontSize: 'var(--text-md)', color: 'var(--its-text-primary)' }}>
                      {ctrl.name}
                    </span>
                    <StatusBadge status={ctrl.connection_status} />
                  </div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)', marginTop: '4px', display: 'flex', gap: '12px' }}>
                    <span>Vendor: <b style={{ color: 'var(--its-text-secondary)' }}>{ctrl.vendor} {ctrl.model}</b></span>
                    <span>•</span>
                    <span>Protocol: <span className="mono" style={{ color: 'var(--its-text-cyan)' }}>{ctrl.protocol}</span></span>
                    <span>•</span>
                    <span>Socket: <span className="mono">{ctrl.ip_address}:{ctrl.port}</span></span>
                    <span>•</span>
                    <span>Mode: <span className="mono">{ctrl.control_mode}</span></span>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={() => handleTestConnection(ctrl.id)}
                    className="its-btn"
                    disabled={testingId === ctrl.id}
                  >
                    <RefreshCw size={13} className={testingId === ctrl.id ? 'pulse-indicator' : ''} />
                    <span>{testingId === ctrl.id ? 'Pinging Socket...' : 'Test Reachability'}</span>
                  </button>

                  <button
                    onClick={() => {
                      setSelectedCtrl(ctrl);
                      setTargetPhase(ctrl.active_phase || 2);
                      setCommandReport(null);
                    }}
                    className="its-btn its-btn-primary"
                  >
                    <Play size={13} />
                    <span>Dispatch Phase Hold</span>
                  </button>
                </div>
              </div>

              {/* Ring Barrier State */}
              <RingBarrierDiagram
                phases={ctrl.phases}
                activePhase={ctrl.active_phase}
                activeSeconds={24}
              />
            </div>
          ))}
        </div>
      )}

      {/* --------------------------------------------------------------------
          Industrial Command Confirmation Dialog (Section 40 & 92)
          -------------------------------------------------------------------- */}
      {selectedCtrl && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.45)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '20px',
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '600px',
              background: 'var(--its-bg-surface)',
              border: '1px solid var(--its-border-accent)',
              borderRadius: 'var(--radius-lg)',
              boxShadow: 'var(--shadow-lg), 0 0 24px rgba(56, 189, 248, 0.15)',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: '16px 20px',
                background: 'var(--its-bg-subsurface)',
                borderBottom: '1px solid var(--its-border-subtle)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div>
                <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 800, letterSpacing: '0.04em', color: 'var(--its-text-primary)' }}>
                  DISPATCH SIGNAL PHASE OVERRIDE
                </h2>
                <div style={{ fontSize: '0.6875rem', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
                  TARGET: {selectedCtrl.name} ({selectedCtrl.ip_address}:{selectedCtrl.port})
                </div>
              </div>
              <button
                onClick={() => setSelectedCtrl(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleIssueCommand} style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Operator Identity & Safety Interlock Banner */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: 'rgba(56, 189, 248, 0.08)',
                  border: '1px solid rgba(56, 189, 248, 0.25)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '10px 14px',
                  fontSize: 'var(--text-xs)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <UserCheck size={16} color="var(--its-text-cyan)" />
                  <span>OPERATOR: <b>{user?.username || 'admin'}</b> ({user?.role || 'OPERATOR'})</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#10b981', fontFamily: 'var(--font-mono)' }}>
                  <ShieldCheck size={14} />
                  <span>SAFETY INTERLOCK: ACTIVE</span>
                </div>
              </div>

              {/* Side-by-Side State Diff */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '12px', alignItems: 'center' }}>
                {/* Current State */}
                <div style={{ background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                  <div className="metric-label">CURRENT PHASE</div>
                  <div style={{ fontSize: 'var(--text-lg)', fontWeight: 700, color: '#34d399', fontFamily: 'var(--font-mono)' }}>
                    Φ{selectedCtrl.active_phase || 2}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '2px' }}>
                    Holding Normal Cycle
                  </div>
                </div>

                <ArrowRight size={20} color="var(--its-text-muted)" />

                {/* Requested State */}
                <div style={{ background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-accent)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                  <div className="metric-label" style={{ color: 'var(--its-text-cyan)' }}>REQUESTED PHASE</div>
                  <div style={{ fontSize: 'var(--text-lg)', fontWeight: 700, color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>
                    Φ{targetPhase}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '2px' }}>
                    Hold Duration: {duration}s
                  </div>
                </div>
              </div>

              {/* Form Controls */}
              <div className="grid-2">
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Select Target Phase
                  </label>
                  <select
                    className="its-select"
                    value={targetPhase}
                    onChange={(e) => setTargetPhase(parseInt(e.target.value, 10))}
                  >
                    {selectedCtrl.phases?.map((p: any) => (
                      <option key={p.phase_number} value={p.phase_number}>
                        Phase {p.phase_number}: {p.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Hold Duration (Seconds)
                  </label>
                  <input
                    type="number"
                    min="5"
                    max="120"
                    className="its-input"
                    value={duration}
                    onChange={(e) => setDuration(parseInt(e.target.value, 10))}
                    required
                  />
                </div>
              </div>

              {/* Safety Engine Report Output */}
              {commandReport && (
                <div
                  style={{
                    padding: '12px',
                    borderRadius: 'var(--radius-sm)',
                    border: `1px solid ${commandReport.safety_check_passed ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'}`,
                    background: commandReport.safety_check_passed ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, fontSize: 'var(--text-xs)', color: commandReport.safety_check_passed ? '#34d399' : '#f87171' }}>
                    {commandReport.safety_check_passed ? <ShieldCheck size={16} /> : <ShieldAlert size={16} />}
                    <span>SAFETY VERIFICATION: {commandReport.status}</span>
                  </div>

                  {!commandReport.safety_check_passed && commandReport.safety_report?.violations?.length > 0 && (
                    <ul style={{ marginTop: '8px', paddingLeft: '20px', fontSize: 'var(--text-xs)', color: '#f87171' }}>
                      {commandReport.safety_report.violations.map((v: string, idx: number) => (
                        <li key={idx}>{v}</li>
                      ))}
                    </ul>
                  )}

                  {commandReport.safety_check_passed && (
                    <div style={{ marginTop: '4px', fontSize: 'var(--text-xs)', color: '#34d399' }}>
                      Deterministic check passed. Command dispatched to physical socket at {commandReport.acknowledged_at}.
                    </div>
                  )}
                </div>
              )}

              {/* Modal Actions */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
                <button type="button" onClick={() => setSelectedCtrl(null)} className="its-btn">
                  Cancel
                </button>
                <button type="submit" className="its-btn its-btn-primary" disabled={issuing}>
                  {issuing ? 'Validating NEMA Safety...' : 'Confirm & Execute Command'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
