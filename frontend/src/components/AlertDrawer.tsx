import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, AlertTriangle, ShieldAlert, Bell, CheckCircle2, ArrowUpRight } from 'lucide-react';
import { api } from '../api/client';

interface AlertDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AlertDrawer: React.FC<AlertDrawerProps> = ({ isOpen, onClose }) => {
  const [alerts, setAlerts] = useState<any[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      api.getDashboardSummary()
        .then(summary => {
          setAlerts(summary.alerts?.items || []);
          setIncidents(summary.incidents?.items || []);
        })
        .catch(() => {
          setAlerts([]);
          setIncidents([]);
        })
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer-panel">
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Bell size={18} color="var(--its-text-accent)" />
            <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, letterSpacing: '0.04em', color: 'var(--its-text-primary)' }}>
              OPERATIONAL ALERTS & NOTIFICATIONS
            </span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--its-text-muted)',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            <X size={18} />
          </button>
        </div>

        <div className="drawer-body">
          {loading ? (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--its-text-muted)', fontSize: 'var(--text-xs)' }}>
              Polling active alert streams...
            </div>
          ) : alerts.length === 0 && incidents.length === 0 ? (
            <div style={{
              padding: '40px 20px',
              textAlign: 'center',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '12px'
            }}>
              <CheckCircle2 size={36} color="var(--its-signal-green)" />
              <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--its-text-primary)' }}>
                NO UNACKNOWLEDGED ALERTS
              </div>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)', maxWidth: '280px' }}>
                All signal controllers, detection loops, and safety engines are currently within nominal thresholds.
              </p>
            </div>
          ) : (
            <>
              {incidents.length > 0 && (
                <div>
                  <div style={{
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    color: '#b91c1c',
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    marginBottom: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    <ShieldAlert size={14} /> Active Incidents ({incidents.length})
                  </div>
                  {incidents.map(inc => (
                    <div
                      key={inc.id}
                      style={{
                        padding: '12px',
                        background: '#fef2f2',
                        border: '1px solid #fecaca',
                        borderRadius: 'var(--radius-md)',
                        marginBottom: '8px'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                        <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: '#0f172a' }}>
                          {inc.title}
                        </span>
                        <span className={`status-badge ${inc.severity.toLowerCase()}`}>
                          {inc.severity}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#475569', marginBottom: '8px' }}>
                        Type: {inc.type} • Status: {inc.status}
                      </div>
                      <button
                        className="its-btn its-btn-danger"
                        style={{ fontSize: '0.7rem', padding: '3px 8px', width: '100%', justifyContent: 'space-between' }}
                        onClick={() => {
                          onClose();
                          navigate('/incidents');
                        }}
                      >
                        <span>Dispatch / Review Incident</span>
                        <ArrowUpRight size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {alerts.length > 0 && (
                <div>
                  <div style={{
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    color: '#fbbf24',
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    marginBottom: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    <AlertTriangle size={14} /> System Alerts ({alerts.length})
                  </div>
                  {alerts.map(alt => (
                    <div
                      key={alt.id}
                      style={{
                        padding: '12px',
                        background: 'var(--its-bg-subsurface)',
                        border: '1px solid var(--its-border-subtle)',
                        borderRadius: 'var(--radius-md)',
                        marginBottom: '8px'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--its-text-primary)' }}>
                          {alt.title}
                        </span>
                        <span className={`status-badge ${alt.severity?.toLowerCase() || 'warning'}`}>
                          {alt.severity || 'WARN'}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--its-text-muted)' }}>
                        Category: {alt.category || 'CONTROLLER_TELEMETRY'}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
};
