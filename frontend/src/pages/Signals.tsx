import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { SignalCommandWorkflow } from '../components/SignalCommandWorkflow';
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

  // Commands are never issued straight from this page. Opening the guided
  // workflow forces the propose -> validate -> confirm sequence, so an
  // operator always sees the per-rule Safety Engine verdict on real, freshly
  // read controller state before anything reaches the hardware.
  const [workflowControllerId, setWorkflowControllerId] = useState<string | null | undefined>(undefined);

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

            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div
                style={{
                  padding: '12px 14px',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--its-border-subtle)',
                  background: 'var(--its-bg-subsurface)',
                  fontSize: 'var(--text-2xs)',
                  color: 'var(--its-text-secondary)',
                  lineHeight: 1.7,
                }}
              >
                <div style={{ fontWeight: 700, color: 'var(--its-text-primary)', marginBottom: '5px' }}>
                  GUIDED COMMAND WORKFLOW
                </div>
                Signal changes go through a four-step flow: propose, validate against the
                Deterministic Safety Engine on freshly read controller state, confirm, then
                audit. The validation step shows every rule with its own pass or fail and a
                plain-language explanation, and writes nothing.
              </div>

              {selectedCtrl && selectedCtrl.connection_status !== 'CONNECTED' && (
                <div
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--its-signal-yellow-border)',
                    background: 'var(--its-signal-yellow-bg)',
                    fontSize: 'var(--text-2xs)',
                    lineHeight: 1.6,
                  }}
                >
                  <strong>{selectedCtrl.name}</strong> is {selectedCtrl.connection_status}. The
                  Safety Engine refuses commands to hardware whose phase state cannot be read;
                  the validation step will show exactly which rule stops it.
                </div>
              )}

              <button
                type="button"
                onClick={() => setWorkflowControllerId(selectedCtrl?.id ?? null)}
                className="its-btn its-btn-primary"
                disabled={!selectedCtrl}
                style={{ justifyContent: 'center' }}
              >
                <ShieldCheck size={14} />
                <span>Open guided command workflow</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {workflowControllerId !== undefined && (
        <SignalCommandWorkflow
          controllers={controllers}
          preselectedControllerId={workflowControllerId}
          onClose={() => setWorkflowControllerId(undefined)}
          onExecuted={loadControllers}
        />
      )}
    </div>
  );
};
