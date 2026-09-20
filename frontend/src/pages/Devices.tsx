import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { Cpu, RefreshCw, Plus, X } from 'lucide-react';

export const Devices: React.FC = () => {
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [pingingId, setPingingId] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  const [name, setName] = useState('');
  const [type, setType] = useState('CONTROLLER');
  const [ip, setIp] = useState('192.168.1.100');
  const [port, setPort] = useState(501);

  const loadDevices = async () => {
    try {
      const data = await api.getDevices();
      setDevices(data);
    } catch (err) {
      console.error('Failed to load devices', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDevices();
  }, []);

  const handlePing = async (id: string) => {
    setPingingId(id);
    try {
      const res = await api.pingDevice(id);
      await loadDevices();
      alert(`Ping result for ${res.name}: ${res.status} (Latency: ${res.latency_ms ? `${res.latency_ms}ms` : 'Unreachable'})`);
    } catch (err: any) {
      alert(`Ping error: ${err.message}`);
    } finally {
      setPingingId(null);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.registerDevice({
        name,
        device_type: type,
        ip_address: ip,
        port: port,
      });
      setShowModal(false);
      setName('');
      await loadDevices();
    } catch (err: any) {
      alert(`Registration error: ${err.message}`);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>Physical Roadside Devices & Cabinet Health</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Direct network telemetry, socket ping latency, and firmware verification for field assets.
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="its-btn its-btn-primary">
          <Plus size={16} />
          <span>Register Field Device</span>
        </button>
      </div>

      {devices.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="NO FIELD DEVICES CONFIGURED"
          description="No roadside devices, signal cabinets, MMU monitors, or sensor processors have been registered."
          actionText="Register Device"
          actionLink="#"
          icon={<Cpu size={36} />}
        />
      ) : (
        <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="its-table">
            <thead>
              <tr>
                <th>Device Name</th>
                <th>Type</th>
                <th>Network IP & Port</th>
                <th>Ping Latency</th>
                <th>Firmware</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.id}>
                  <td style={{ fontWeight: 600 }}>{d.name}</td>
                  <td style={{ fontSize: 'var(--text-xs)' }}>{d.device_type}</td>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                    {d.ip_address ? `${d.ip_address}:${d.port || 80}` : 'UNCONFIGURED'}
                  </td>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                    {d.health_metrics?.latency_ms ? `${d.health_metrics.latency_ms} ms` : '—'}
                  </td>
                  <td style={{ fontSize: 'var(--text-xs)' }}>{d.firmware_version || 'v1.0.4-NEMA'}</td>
                  <td><StatusBadge status={d.status} /></td>
                  <td>
                    <button
                      onClick={() => handlePing(d.id)}
                      className="its-btn"
                      style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                      disabled={pingingId === d.id}
                    >
                      <RefreshCw size={12} className={pingingId === d.id ? 'animate-spin' : ''} />
                      <span>{pingingId === d.id ? 'Pinging...' : 'Ping Test'}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '460px',
              background: 'var(--its-bg-surface)',
              border: '1px solid var(--its-border-subtle)',
              borderRadius: 'var(--radius-lg)',
              padding: '24px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>Register Field Device</h2>
              <button onClick={() => setShowModal(false)} style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleRegister}>
              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Device Name
                </label>
                <input type="text" className="its-input" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Device Type
                </label>
                <select className="its-select" value={type} onChange={(e) => setType(e.target.value)}>
                  <option value="CONTROLLER">Signal Controller Cabinet</option>
                  <option value="RADAR">Radar Vehicle Detector</option>
                  <option value="CAMERA">Surveillance IP Camera</option>
                  <option value="WEATHER_STATION">Roadside Weather Station</option>
                </select>
              </div>

              <div className="grid-2" style={{ marginBottom: '20px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                    IP Address
                  </label>
                  <input type="text" className="its-input" value={ip} onChange={(e) => setIp(e.target.value)} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                    Port
                  </label>
                  <input type="number" className="its-input" value={port} onChange={(e) => setPort(parseInt(e.target.value, 10))} />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="its-btn">Cancel</button>
                <button type="submit" className="its-btn its-btn-primary">Register</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
