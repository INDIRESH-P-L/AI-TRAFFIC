import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { FileText, RefreshCw } from 'lucide-react';

export const Audit: React.FC = () => {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState<string>('');

  const loadLogs = async () => {
    try {
      const data = await api.getAuditLogs(actionFilter);
      setLogs(data);
    } catch (err) {
      console.error('Failed to load audit logs', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [actionFilter]);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>Immutable System Audit Log</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Permanent ledger of operator commands, configuration changes, and deterministic safety checks.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <select
            className="its-select"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={{ width: '220px' }}
          >
            <option value="">All Operational Actions</option>
            <option value="USER_LOGIN">User Login</option>
            <option value="SIGNAL_COMMAND_ISSUED">Signal Command Issued</option>
            <option value="SIGNAL_COMMAND_REJECTED_BY_SAFETY">Rejected by Safety</option>
            <option value="CREATE_INTERSECTION">Create Intersection</option>
            <option value="INCIDENT_STATUS_TRANSITION">Incident Transition</option>
          </select>

          <button onClick={loadLogs} className="its-btn">
            <RefreshCw size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {logs.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="AUDIT LEDGER EMPTY"
          description="No audited events matching the selected filter were found."
          icon={<FileText size={36} />}
        />
      ) : (
        <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="its-table">
            <thead>
              <tr>
                <th>Timestamp (UTC)</th>
                <th>Operator / Actor</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Result</th>
                <th>Payload / Evidence Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                    {new Date(log.timestamp).toISOString().replace('T', ' ').slice(0, 19)}
                  </td>
                  <td style={{ fontWeight: 600 }}>{log.actor_username}</td>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)', color: '#58a6ff' }}>{log.action}</td>
                  <td style={{ fontSize: 'var(--text-xs)' }}>{log.resource_type} ({log.resource_id?.slice(0, 8) || 'Global'})</td>
                  <td><StatusBadge status={log.result} /></td>
                  <td className="mono" style={{ fontSize: '0.7rem', color: 'var(--its-text-muted)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {log.details ? JSON.stringify(log.details) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
