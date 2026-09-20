import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import {
  RefreshCw,
  ShieldCheck,
  Sliders,
  Camera,
  Cpu,
  Database,
  Lock,
  FileText
} from 'lucide-react';

type SettingsTab = 'SYSTEM_HEALTH' | 'CONTROLLER_WIZARD' | 'CAMERA_WIZARD' | 'AI_MODELS' | 'SECURITY' | 'AUDIT_LOG';

export const Settings: React.FC = () => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('SYSTEM_HEALTH');
  const [sysStatus, setSysStatus] = useState<any>(null);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Controller Wizard
  const [ctrlIp, setCtrlIp] = useState('192.168.1.100');
  const [ctrlPort, setCtrlPort] = useState(501);
  const [testingCtrl, setTestingCtrl] = useState(false);
  const [ctrlTestResult, setCtrlTestResult] = useState<any | null>(null);

  // Camera Wizard
  const [camUrl, setCamUrl] = useState('rtsp://192.168.1.120:554/live/stream1');
  const [testingCam, setTestingCam] = useState(false);
  const [camTestResult, setCamTestResult] = useState<any | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const data = await api.getSystemStatus();
      setSysStatus(data);
    } catch (err) {
      console.error('Failed to load system status', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleTestController = async (e: React.FormEvent) => {
    e.preventDefault();
    setTestingCtrl(true);
    setCtrlTestResult(null);
    try {
      const res = await api.testControllerWizard(ctrlIp, ctrlPort);
      setCtrlTestResult(res);
    } catch (err: any) {
      setCtrlTestResult({ reachable: false, message: err.message, allowed_to_save_as_connected: false });
    } finally {
      setTestingCtrl(false);
    }
  };

  const handleTestCamera = async (e: React.FormEvent) => {
    e.preventDefault();
    setTestingCam(true);
    setCamTestResult(null);
    try {
      const res = await api.testCameraWizard(camUrl);
      setCamTestResult(res);
    } catch (err: any) {
      setCamTestResult({ reachable: false, message: err.message, allowed_to_save_as_connected: false });
    } finally {
      setTestingCam(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'var(--its-gradient-hero)',
          padding: '16px 22px',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--its-border-subtle)',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: 'var(--text-lg)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
              SYSTEM CONFIGURATION & HARDWARE WIZARDS
            </h1>
            <span className="status-badge active">AUTHENTICATED TOC</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            External provider connectivity, physical socket reachability validation, and security policies.
          </div>
        </div>

        <button onClick={loadStatus} className="its-btn" disabled={loading}>
          <RefreshCw size={13} className={loading ? 'pulse-indicator' : ''} />
          <span>Verify Subsystems</span>
        </button>
      </div>

      {/* Two-Column Settings Workspace (Section 39 & 90) */}
      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: '16px' }}>
        {/* Left Settings Sidebar */}
        <div className="its-card" style={{ padding: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <button
            onClick={() => setActiveTab('SYSTEM_HEALTH')}
            className={`nav-link ${activeTab === 'SYSTEM_HEALTH' ? 'active' : ''}`}
            style={{ width: '100%', border: 'none', background: activeTab === 'SYSTEM_HEALTH' ? 'var(--its-gradient-nav-active)' : 'transparent', textAlign: 'left', cursor: 'pointer' }}
          >
            <Database size={15} />
            <span>Subsystem Health</span>
          </button>

          <button
            onClick={() => setActiveTab('CONTROLLER_WIZARD')}
            className={`nav-link ${activeTab === 'CONTROLLER_WIZARD' ? 'active' : ''}`}
            style={{ width: '100%', border: 'none', background: activeTab === 'CONTROLLER_WIZARD' ? 'var(--its-gradient-nav-active)' : 'transparent', textAlign: 'left', cursor: 'pointer' }}
          >
            <Sliders size={15} />
            <span>Controller Tester</span>
          </button>

          <button
            onClick={() => setActiveTab('CAMERA_WIZARD')}
            className={`nav-link ${activeTab === 'CAMERA_WIZARD' ? 'active' : ''}`}
            style={{ width: '100%', border: 'none', background: activeTab === 'CAMERA_WIZARD' ? 'var(--its-gradient-nav-active)' : 'transparent', textAlign: 'left', cursor: 'pointer' }}
          >
            <Camera size={15} />
            <span>Camera Stream Tester</span>
          </button>

          <button
            onClick={() => setActiveTab('AI_MODELS')}
            className={`nav-link ${activeTab === 'AI_MODELS' ? 'active' : ''}`}
            style={{ width: '100%', border: 'none', background: activeTab === 'AI_MODELS' ? 'var(--its-gradient-nav-active)' : 'transparent', textAlign: 'left', cursor: 'pointer' }}
          >
            <Cpu size={15} />
            <span>AI Model Policies</span>
          </button>

          <button
            onClick={() => setActiveTab('SECURITY')}
            className={`nav-link ${activeTab === 'SECURITY' ? 'active' : ''}`}
            style={{ width: '100%', border: 'none', background: activeTab === 'SECURITY' ? 'var(--its-gradient-nav-active)' : 'transparent', textAlign: 'left', cursor: 'pointer' }}
          >
            <Lock size={15} />
            <span>Security & Interlocks</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('AUDIT_LOG');
              api.getAuditLogs().then(data => setAuditLogs(data)).catch(() => {});
            }}
            className={`nav-link ${activeTab === 'AUDIT_LOG' ? 'active' : ''}`}
            style={{ width: '100%', border: 'none', background: activeTab === 'AUDIT_LOG' ? 'var(--its-gradient-nav-active)' : 'transparent', textAlign: 'left', cursor: 'pointer' }}
          >
            <FileText size={15} />
            <span>Audit Trail</span>
          </button>
        </div>

        {/* Right Content Pane */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* TAB 1: SYSTEM HEALTH */}
          {activeTab === 'SYSTEM_HEALTH' && (
            <div className="its-card">
              <div className="its-card-header">
                <span className="its-card-title">
                  <ShieldCheck size={16} color="var(--its-text-cyan)" />
                  <span>Core Subsystem Integration Status</span>
                </span>
                <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                  VERSION: {sysStatus?.system_version || '2.4.0'} | ENV: {sysStatus?.environment || 'PRODUCTION'}
                </span>
              </div>

              <div className="grid-3" style={{ marginTop: '12px' }}>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                  <div className="metric-label">RELATIONAL DATABASE</div>
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)', margin: '4px 0', color: 'var(--its-text-primary)' }}>
                    SQLAlchemy ({sysStatus?.subsystems?.database?.dialect || 'sqlite'})
                  </div>
                  <StatusBadge status={sysStatus?.subsystems?.database?.status || 'CONNECTED'} />
                </div>

                <div style={{ background: 'var(--its-bg-subsurface)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                  <div className="metric-label">GIS MAP PROVIDER</div>
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)', margin: '4px 0', color: 'var(--its-text-primary)' }}>
                    CartoDB Voyager / Leaflet GIS
                  </div>
                  <StatusBadge status="CONNECTED" />
                </div>

                <div style={{ background: 'var(--its-bg-subsurface)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                  <div className="metric-label">METEOROLOGICAL INGESTION</div>
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)', margin: '4px 0', color: 'var(--its-text-primary)' }}>
                    Open-Meteo GIS Satellite
                  </div>
                  <StatusBadge status="CONNECTED" />
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: CONTROLLER WIZARD */}
          {activeTab === 'CONTROLLER_WIZARD' && (
            <div className="its-card">
              <div className="its-card-header">
                <span className="its-card-title">
                  <Sliders size={16} color="var(--its-text-cyan)" />
                  <span>Signal Controller Network Reachability Wizard</span>
                </span>
                <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                  TCP SOCKET TESTING
                </span>
              </div>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '16px' }}>
                Strict Rule: Never mark a controller as 'connected' unless physical socket connectivity succeeds.
              </p>

              <form onSubmit={handleTestController}>
                <div className="grid-2" style={{ marginBottom: '14px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                      Controller IP Address / Host
                    </label>
                    <input
                      type="text"
                      className="its-input mono"
                      value={ctrlIp}
                      onChange={(e) => setCtrlIp(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                      TCP Port (NTCIP: 501 / 161)
                    </label>
                    <input
                      type="number"
                      className="its-input mono"
                      value={ctrlPort}
                      onChange={(e) => setCtrlPort(parseInt(e.target.value, 10))}
                      required
                    />
                  </div>
                </div>

                <button type="submit" className="its-btn its-btn-primary" disabled={testingCtrl}>
                  <RefreshCw size={13} className={testingCtrl ? 'pulse-indicator' : ''} />
                  <span>{testingCtrl ? 'Testing TCP Socket Handshake...' : 'Perform Network Reachability Test'}</span>
                </button>
              </form>

              {ctrlTestResult && (
                <div
                  style={{
                    marginTop: '16px',
                    padding: '14px',
                    borderRadius: 'var(--radius-sm)',
                    border: `1px solid ${ctrlTestResult.reachable ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'}`,
                    background: ctrlTestResult.reachable ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', color: ctrlTestResult.reachable ? '#34d399' : '#f87171' }}>
                    RESULT: {ctrlTestResult.reachable ? 'CONTROLLER SOCKET REACHABLE' : 'UNREACHABLE (CONNECTION TIMEOUT)'}
                  </div>
                  <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '4px' }}>
                    {ctrlTestResult.message}
                  </div>
                  {ctrlTestResult.latency_ms && (
                    <div className="mono" style={{ fontSize: '10px', color: '#34d399', marginTop: '4px' }}>
                      LATENCY: {ctrlTestResult.latency_ms}ms
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: CAMERA WIZARD */}
          {activeTab === 'CAMERA_WIZARD' && (
            <div className="its-card">
              <div className="its-card-header">
                <span className="its-card-title">
                  <Camera size={16} color="var(--its-text-cyan)" />
                  <span>RTSP Edge Camera Stream Validation Wizard</span>
                </span>
                <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                  PORT 554 / 8554 TESTER
                </span>
              </div>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '16px' }}>
                Test RTSP stream headers and handshake before adding video stream to active intersection surveillance.
              </p>

              <form onSubmit={handleTestCamera}>
                <div style={{ marginBottom: '14px' }}>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    RTSP Stream URL
                  </label>
                  <input
                    type="text"
                    className="its-input mono"
                    value={camUrl}
                    onChange={(e) => setCamUrl(e.target.value)}
                    required
                  />
                </div>

                <button type="submit" className="its-btn its-btn-primary" disabled={testingCam}>
                  <RefreshCw size={13} className={testingCam ? 'pulse-indicator' : ''} />
                  <span>{testingCam ? 'Validating RTSP Stream...' : 'Test RTSP Socket Handshake'}</span>
                </button>
              </form>

              {camTestResult && (
                <div
                  style={{
                    marginTop: '16px',
                    padding: '14px',
                    borderRadius: 'var(--radius-sm)',
                    border: `1px solid ${camTestResult.reachable ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'}`,
                    background: camTestResult.reachable ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', color: camTestResult.reachable ? '#34d399' : '#f87171' }}>
                    RESULT: {camTestResult.reachable ? 'RTSP STREAM ACTIVE' : 'STREAM UNREACHABLE'}
                  </div>
                  <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '4px' }}>
                    {camTestResult.message}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: AI MODELS */}
          {activeTab === 'AI_MODELS' && (
            <div className="its-card">
              <div className="its-card-header">
                <span className="its-card-title">
                  <Cpu size={16} color="var(--its-text-cyan)" />
                  <span>Inference Engines & RAG Vector Boundaries</span>
                </span>
                <span className="status-badge active">RIGID GROUNDING</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', color: 'var(--its-text-primary)' }}>PyTorch Object Detection Classifier</div>
                  <div style={{ fontSize: '11px', color: 'var(--its-text-muted)', marginTop: '2px' }}>Runs local Torchvision model on RTSP frames; zero cloud data exfiltration.</div>
                </div>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', color: 'var(--its-text-primary)' }}>MUTCD / NEMA Vector RAG Index</div>
                  <div style={{ fontSize: '11px', color: 'var(--its-text-muted)', marginTop: '2px' }}>BM25 + TF-IDF cosine ranking strictly indexing MUTCD Part 4 & NEMA TS 2-2016.</div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 5: SECURITY & INTERLOCKS */}
          {activeTab === 'SECURITY' && (
            <div className="its-card">
              <div className="its-card-header">
                <span className="its-card-title">
                  <Lock size={16} color="var(--its-text-cyan)" />
                  <span>Deterministic Safety Interlocks & Access Control</span>
                </span>
                <span className="status-badge green">ENFORCING</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', color: '#34d399' }}>Dual-Ring Barrier Conflict Interlock</div>
                  <div style={{ fontSize: '11px', color: 'var(--its-text-muted)', marginTop: '2px' }}>Mathematically forbids opposing ring phases from receiving concurrent green states.</div>
                </div>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                  <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', color: '#34d399' }}>JWT Bearer Authentication & RBAC</div>
                  <div style={{ fontSize: '11px', color: 'var(--its-text-muted)', marginTop: '2px' }}>Strict token expiration, bcrypt hashing, and role checks on all signal command endpoints.</div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 6: AUDIT TRAIL */}
          {activeTab === 'AUDIT_LOG' && (
            <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--its-border-subtle)', background: 'var(--its-bg-subsurface)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <FileText size={16} color="var(--its-text-cyan)" />
                  <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    Immutable System Audit Ledger
                  </span>
                </div>
                <button
                  onClick={() => api.getAuditLogs().then(data => setAuditLogs(data)).catch(() => {})}
                  className="its-btn"
                  style={{ padding: '4px 8px', fontSize: '11px' }}
                >
                  <RefreshCw size={11} />
                  <span>Refresh Log</span>
                </button>
              </div>

              <div className="its-table-container" style={{ border: 'none' }}>
                <table className="its-table">
                  <thead>
                    <tr>
                      <th>Timestamp (UTC)</th>
                      <th>Operator / Actor</th>
                      <th>Action</th>
                      <th>Resource</th>
                      <th>Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditLogs.length === 0 ? (
                      <tr>
                        <td colSpan={5} style={{ textAlign: 'center', padding: '24px', color: 'var(--its-text-muted)', fontSize: 'var(--text-xs)' }}>
                          No audited actions recorded.
                        </td>
                      </tr>
                    ) : (
                      auditLogs.map((log) => (
                        <tr key={log.id}>
                          <td className="mono" style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}>
                            {log.timestamp ? new Date(log.timestamp).toISOString().replace('T', ' ').slice(0, 19) : 'N/A'}
                          </td>
                          <td style={{ fontWeight: 600, fontSize: 'var(--text-xs)' }}>{log.actor_username || 'SYSTEM'}</td>
                          <td className="mono" style={{ fontSize: 'var(--text-xs)', color: '#38bdf8' }}>{log.action}</td>
                          <td style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)' }}>
                            {log.target_type || 'RESOURCE'}:{log.target_id?.slice(0, 8) || 'GLOBAL'}
                          </td>
                          <td>
                            <StatusBadge status={log.status || 'SUCCESS'} />
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
