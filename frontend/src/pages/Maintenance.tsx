import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { Wrench, Plus, CheckCircle2, X } from 'lucide-react';

export const Maintenance: React.FC = () => {
  const [events, setEvents] = useState<any[]>([]);
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);

  const [deviceId, setDeviceId] = useState('');
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [technician, setTechnician] = useState('');

  const load = async () => {
    try {
      const [evs, devs] = await Promise.all([
        api.getMaintenanceEvents(),
        api.getDevices(),
      ]);
      setEvents(evs);
      setDevices(devs);
      if (devs.length > 0 && !deviceId) {
        setDeviceId(devs[0].id);
      }
    } catch (err) {
      console.error('Failed to load maintenance events', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createMaintenanceOrder({
        device_id: deviceId,
        title,
        description: desc,
        technician_name: technician,
      });
      setShowModal(false);
      setTitle('');
      setDesc('');
      setTechnician('');
      await load();
    } catch (err: any) {
      alert(`Error creating maintenance order: ${err.message}`);
    }
  };

  const handleComplete = async (id: string) => {
    try {
      await api.completeMaintenance(id);
      await load();
    } catch (err: any) {
      alert(`Failed to complete: ${err.message}`);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>Field Maintenance & Hardware Work Orders</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Scheduled calibration, MMU certification, conflict monitor tests, and sensor repairs.
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="its-btn its-btn-primary">
          <Plus size={16} />
          <span>New Work Order</span>
        </button>
      </div>

      {events.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="NO MAINTENANCE WORK ORDERS"
          description="There are currently no active or scheduled field maintenance orders recorded in the registry."
          actionText="Create Work Order"
          actionLink="#"
          icon={<Wrench size={36} />}
        />
      ) : (
        <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="its-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Device ID</th>
                <th>Technician</th>
                <th>Scheduled Date</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr key={ev.id}>
                  <td style={{ fontWeight: 600 }}>{ev.title}</td>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>{ev.device_id}</td>
                  <td>{ev.technician_name || 'Unassigned'}</td>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                    {new Date(ev.scheduled_date).toLocaleDateString()}
                  </td>
                  <td><StatusBadge status={ev.status} /></td>
                  <td>
                    {ev.status !== 'COMPLETED' && (
                      <button
                        onClick={() => handleComplete(ev.id)}
                        className="its-btn"
                        style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                      >
                        <CheckCircle2 size={12} />
                        <span>Sign Off</span>
                      </button>
                    )}
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
              maxWidth: '480px',
              background: 'var(--its-bg-surface)',
              border: '1px solid var(--its-border-subtle)',
              borderRadius: 'var(--radius-lg)',
              padding: '24px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>Create Field Work Order</h2>
              <button onClick={() => setShowModal(false)} style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreate}>
              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Work Order Title (e.g. Annual MMU Conflict Monitor Bench Test)
                </label>
                <input type="text" className="its-input" value={title} onChange={(e) => setTitle(e.target.value)} required />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Target Device
                </label>
                <select className="its-select" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
                  {devices.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} ({d.device_type})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Description / Failure Notes
                </label>
                <input type="text" className="its-input" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. Cabinet moisture seal integrity failure" />
              </div>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Assigned Technician
                </label>
                <input type="text" className="its-input" value={technician} onChange={(e) => setTechnician(e.target.value)} placeholder="e.g. J. Doe, IMSA Level II" />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="its-btn">Cancel</button>
                <button type="submit" className="its-btn its-btn-primary">Schedule Order</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
