import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { TrendingUp, Plus, X } from 'lucide-react';
import { Link } from 'react-router-dom';

export const Corridors: React.FC = () => {
  const [corridors, setCorridors] = useState<any[]>([]);
  const [intersections, setIntersections] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [mode, setMode] = useState('GREEN_WAVE');
  const [cycle, setCycle] = useState(90);

  const load = useCallback(async () => {
    try {
      const [corrData, interData] = await Promise.all([
        api.getCorridors(),
        api.getIntersections(),
      ]);
      setCorridors(corrData);
      setIntersections(interData);
    } catch (err) {
      console.error('Failed to load corridors', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createCorridor({
        name,
        description: desc,
        coordination_mode: mode,
        cycle_length_sec: cycle,
      });
      setShowModal(false);
      setName('');
      setDesc('');
      await load();
    } catch (err: any) {
      alert(`Error creating corridor: ${err.message}`);
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
              ARTERIAL CORRIDORS & COORDINATED PROGRESSION
            </h1>
            <span className="status-badge active">GREEN WAVE SYNC</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Multi-intersection progression bands, coordinated cycle lengths, and arterial travel time optimization.
          </div>
        </div>

        <button onClick={() => setShowModal(true)} className="its-btn its-btn-primary">
          <Plus size={14} />
          <span>Define Corridor</span>
        </button>
      </div>

      {corridors.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="NO COORDINATED CORRIDORS DEFINED"
          description="Corridors group sequential intersections along major arterials to enforce uniform cycle lengths and progression bands."
          actionText="Define Corridor"
          actionLink="#"
          icon={<TrendingUp size={36} />}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {corridors.map((c) => (
            <div key={c.id} className="its-card" style={{ padding: '18px' }}>
              <div className="its-card-header">
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontWeight: 800, fontSize: 'var(--text-md)', color: 'var(--its-text-primary)' }}>
                      {c.name}
                    </span>
                    <StatusBadge status={c.coordination_mode} />
                  </div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)', marginTop: '2px' }}>
                    {c.description || 'Regional Arterial Trunk Line'}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '16px', fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)' }}>
                  <div>CYCLE LENGTH: <b style={{ color: 'var(--its-text-cyan)' }}>{c.cycle_length_sec}s</b></div>
                  <div>NODES: <b style={{ color: '#34d399' }}>{c.intersection_count || intersections.length}</b></div>
                </div>
              </div>

              {/* Horizontal Progression Diagram (Section 36) */}
              <div style={{ marginTop: '16px' }}>
                <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '8px', textTransform: 'uppercase' }}>
                  Progressive Signal Coordination Chain
                </div>
                <div
                  style={{
                    background: 'var(--its-bg-subsurface)',
                    border: '1px solid var(--its-border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    padding: '16px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    overflowX: 'auto',
                    gap: '12px',
                  }}
                >
                  {intersections.slice(0, 4).map((inter, idx, arr) => (
                    <React.Fragment key={inter.id}>
                      <Link
                        to={`/intersections/${inter.id}`}
                        style={{
                          textDecoration: 'none',
                          background: 'var(--its-bg-surface)',
                          border: '1px solid var(--its-border-accent)',
                          borderRadius: 'var(--radius-sm)',
                          padding: '10px 14px',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '2px',
                          minWidth: '160px',
                          boxShadow: 'var(--shadow-sm)',
                        }}
                      >
                        <div style={{ fontSize: '10px', color: 'var(--its-text-cyan)', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                          NODE {idx + 1}: {inter.code}
                        </div>
                        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                          {inter.name}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                          Offset: <span className="mono" style={{ color: '#34d399' }}>+{idx * 12}s</span>
                        </div>
                      </Link>

                      {idx < arr.length - 1 && (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', flex: 1, minWidth: '60px' }}>
                          <div style={{ height: '2px', width: '100%', background: 'linear-gradient(90deg, #0284c7, #00f0ff)' }} />
                          <span style={{ fontSize: '9px', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>BANDWIDTH: 45%</span>
                        </div>
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
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
              maxWidth: '500px',
              background: 'var(--its-bg-surface)',
              border: '1px solid var(--its-border-accent)',
              borderRadius: 'var(--radius-lg)',
              boxShadow: 'var(--shadow-lg)',
              padding: '20px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 800 }}>Define Coordinated Corridor</h2>
              <button onClick={() => setShowModal(false)} style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Corridor Name
                </label>
                <input
                  type="text"
                  className="its-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Grand Avenue Arterial"
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Description / Highway ID
                </label>
                <input
                  type="text"
                  className="its-input"
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="e.g. Major east-west commuter arterial"
                />
              </div>

              <div className="grid-2">
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Coordination Mode
                  </label>
                  <select className="its-select" value={mode} onChange={(e) => setMode(e.target.value)}>
                    <option value="GREEN_WAVE">Green Wave (Arterial Offset)</option>
                    <option value="CYCLE_HARMONIZATION">Cycle Harmonization</option>
                    <option value="ADAPTIVE_CORRIDOR">Adaptive Real-Time Split</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Cycle Length (sec)
                  </label>
                  <input
                    type="number"
                    min="45"
                    max="180"
                    className="its-input"
                    value={cycle}
                    onChange={(e) => setCycle(parseInt(e.target.value, 10))}
                    required
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="its-btn">
                  Cancel
                </button>
                <button type="submit" className="its-btn its-btn-primary">
                  Save Corridor
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
