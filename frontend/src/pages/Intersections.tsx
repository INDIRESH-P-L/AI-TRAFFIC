import React, { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { GitCommit, Plus, ArrowUpRight, X, Search, Sliders } from 'lucide-react';

export const Intersections: React.FC = () => {
  const [intersections, setIntersections] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // Form State
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [latitude, setLatitude] = useState('37.7749');
  const [longitude, setLongitude] = useState('-122.4194');
  const [jurisdiction, setJurisdiction] = useState('Municipal DOT');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.getIntersections();
      setIntersections(data);
    } catch (err) {
      console.error('Failed to load intersections', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError(null);

    try {
      const payload = {
        name,
        code,
        latitude: parseFloat(latitude),
        longitude: parseFloat(longitude),
        jurisdiction,
        approaches: [
          {
            direction: 'NORTHBOUND',
            road_name: `${name} North`,
            speed_limit_kph: 50,
            lanes: [
              { lane_number: 1, movement_type: 'LEFT_TURN', assigned_phase: 1 },
              { lane_number: 2, movement_type: 'THRU', assigned_phase: 2 },
            ],
          },
          {
            direction: 'EASTBOUND',
            road_name: `${name} East`,
            speed_limit_kph: 50,
            lanes: [
              { lane_number: 1, movement_type: 'THRU', assigned_phase: 4 },
            ],
          },
        ],
      };

      await api.createIntersection(payload);
      setShowModal(false);
      setName('');
      setCode('');
      await load();
    } catch (err: any) {
      setError(err.message || 'Failed to create intersection');
    } finally {
      setCreating(false);
    }
  };

  const filtered = intersections.filter(i =>
    i.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    i.code?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    i.jurisdiction?.toLowerCase().includes(searchQuery.toLowerCase())
  );

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
              INTERSECTION JUNCTION DIRECTORY
            </h1>
            <span className="status-badge active">{intersections.length} REGISTERED</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Authorized physical intersections, geometric approaches, speed limits, and signal phase mappings.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div style={{ position: 'relative' }}>
            <Search size={13} color="var(--its-text-muted)" style={{ position: 'absolute', left: '10px', top: '9px' }} />
            <input
              type="text"
              className="its-input"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Filter nodes..."
              style={{ width: '180px', paddingLeft: '28px', fontSize: '11px', height: '32px' }}
            />
          </div>

          <Link to="/signals" className="its-btn" style={{ textDecoration: 'none' }}>
            <Sliders size={13} />
            <span>Signal Controllers</span>
          </Link>

          <button onClick={() => setShowModal(true)} className="its-btn its-btn-primary">
            <Plus size={14} />
            <span>Add Node</span>
          </button>
        </div>
      </div>

      {intersections.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="NO INTERSECTIONS CONFIGURED"
          description="The system has no configured intersections in its inventory. Administrators can register physical junctions with GIS coordinates and approach geometries."
          actionText="Add First Intersection"
          actionLink="#"
          icon={<GitCommit size={36} />}
        />
      ) : (
        <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="its-table-container" style={{ border: 'none' }}>
            <table className="its-table">
              <thead>
                <tr>
                  <th>Node Code</th>
                  <th>Intersection Name</th>
                  <th>GIS Coordinates</th>
                  <th>Jurisdiction</th>
                  <th>Controller</th>
                  <th>Vision Camera</th>
                  <th>Operational Health</th>
                  <th style={{ textAlign: 'right' }}>Topology</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((inter) => (
                  <tr key={inter.id}>
                    <td className="mono" style={{ fontWeight: 700, color: '#38bdf8' }}>
                      {inter.code}
                    </td>
                    <td style={{ fontWeight: 600, color: 'var(--its-text-primary)' }}>{inter.name}</td>
                    <td className="mono" style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)' }}>
                      {inter.latitude?.toFixed(5)}, {inter.longitude?.toFixed(5)}
                    </td>
                    <td style={{ fontSize: 'var(--text-xs)' }}>{inter.jurisdiction}</td>
                    <td><StatusBadge status={inter.controller_status} /></td>
                    <td><StatusBadge status={inter.camera_status} /></td>
                    <td><StatusBadge status={inter.operational_status} /></td>
                    <td style={{ textAlign: 'right' }}>
                      <Link
                        to={`/intersections/${inter.id}`}
                        className="its-btn"
                        style={{ padding: '4px 10px', fontSize: '11px', textDecoration: 'none' }}
                      >
                        <span>Inspect</span>
                        <ArrowUpRight size={11} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add Intersection Modal */}
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
              maxWidth: '520px',
              background: 'var(--its-bg-surface)',
              border: '1px solid var(--its-border-accent)',
              borderRadius: 'var(--radius-lg)',
              boxShadow: 'var(--shadow-lg)',
              padding: '20px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 800 }}>Register Physical Intersection</h2>
              <button
                onClick={() => setShowModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            {error && (
              <div style={{ padding: '8px 12px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', borderRadius: 'var(--radius-sm)', color: '#f87171', fontSize: '12px', marginBottom: '12px' }}>
                {error}
              </div>
            )}

            <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Intersection Name
                </label>
                <input
                  type="text"
                  className="its-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Market St & 4th St"
                  required
                />
              </div>

              <div className="grid-2">
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Node Code
                  </label>
                  <input
                    type="text"
                    className="its-input mono"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="e.g. INT-101"
                    required
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Jurisdiction
                  </label>
                  <input
                    type="text"
                    className="its-input"
                    value={jurisdiction}
                    onChange={(e) => setJurisdiction(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="grid-2">
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Latitude (WGS84)
                  </label>
                  <input
                    type="number"
                    step="0.000001"
                    className="its-input mono"
                    value={latitude}
                    onChange={(e) => setLatitude(e.target.value)}
                    required
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Longitude (WGS84)
                  </label>
                  <input
                    type="number"
                    step="0.000001"
                    className="its-input mono"
                    value={longitude}
                    onChange={(e) => setLongitude(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="its-btn">
                  Cancel
                </button>
                <button type="submit" className="its-btn its-btn-primary" disabled={creating}>
                  {creating ? 'Registering...' : 'Register Intersection'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
