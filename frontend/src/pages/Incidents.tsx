import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { IncidentLifecyclePanel } from '../components/IncidentLifecyclePanel';
import { OperationsMap } from '../components/map/OperationsMap';
import type { MapData } from '../components/map/OperationsMap';
import {
  AlertTriangle,
  Plus,
  ShieldCheck,
  MapPin,
  X,
  Filter,
  ShieldAlert,
  Check,
  CheckCircle2,
  CircleDot
} from 'lucide-react';

export const Incidents: React.FC = () => {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [intersections, setIntersections] = useState<any[]>([]);
  const [mapData, setMapData] = useState<MapData | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('');

  // Modal State for New Incident
  const [showModal, setShowModal] = useState(false);
  const [title, setTitle] = useState('');
  const [type, setType] = useState('ROAD_OBSTRUCTION');
  const [severity, setSeverity] = useState('MEDIUM');
  const [intersectionId, setIntersectionId] = useState('');
  const [source] = useState('OPERATOR_LOG');
  const [creating, setCreating] = useState(false);
  const [transitioning, setTransitioning] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [incData, interData, layers] = await Promise.all([
        api.getIncidents(statusFilter),
        api.getIntersections(),
        api.getMapLayers(['junctions', 'incidents']).catch(() => null),
      ]);
      setIncidents(incData);
      setIntersections(interData);
      setMapData(layers);

      if (interData.length > 0 && !intersectionId) {
        setIntersectionId(interData[0].id);
      }

      if (incData.length > 0) {
        if (!selectedIncident || !incData.find((i: any) => i.id === selectedIncident.id)) {
          setSelectedIncident(incData[0]);
        } else {
          const fresh = incData.find((i: any) => i.id === selectedIncident.id);
          if (fresh) setSelectedIncident(fresh);
        }
      } else {
        setSelectedIncident(null);
      }
    } catch (err) {
      console.error('Failed to load incident console data', err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, intersectionId, selectedIncident]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!intersectionId) {
      alert('Please configure an intersection first');
      return;
    }
    setCreating(true);
    try {
      await api.createIncident({
        intersection_id: intersectionId,
        title,
        type,
        severity,
        source,
        affected_lanes: [1],
      });
      setShowModal(false);
      setTitle('');
      await loadData();
    } catch (err: any) {
      alert(`Error creating incident: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  const handleTransition = async (id: string, newStatus: string) => {
    setTransitioning(true);
    try {
      await api.updateIncidentStatus(id, {
        status: newStatus,
        operator_notes: `Operator verified transition to ${newStatus}`,
      });
      await loadData();
    } catch (err: any) {
      alert(`Status transition rejected: ${err.message}`);
    } finally {
      setTransitioning(false);
    }
  };

  const selectedIntersection = selectedIncident
    ? intersections.find((i: any) => i.id === selectedIncident.intersection_id)
    : null;

  const lifecycleStages = ['DETECTED', 'SUSPECTED', 'VERIFIED', 'MITIGATED', 'RESOLVED'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', height: 'calc(100vh - 120px)' }}>
      {/* Console Top Bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'var(--its-bg-surface)',
          padding: '12px 18px',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--its-border-subtle)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <h1 style={{ fontSize: 'var(--text-md)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
            INCIDENT COMMAND CONSOLE
          </h1>
          <span className="status-badge active" style={{ fontSize: '10px' }}>
            {incidents.length} EVENTS RECORDED
          </span>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Filter size={13} color="var(--its-text-muted)" />
            <select
              className="its-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              style={{ width: '140px', padding: '5px 8px', fontSize: 'var(--text-xs)' }}
            >
              <option value="">All Lifecycles</option>
              <option value="DETECTED">Detected</option>
              <option value="SUSPECTED">Suspected</option>
              <option value="VERIFIED">Verified</option>
              <option value="ACTIVE">Active</option>
              <option value="MITIGATED">Mitigated</option>
              <option value="RESOLVED">Resolved</option>
            </select>
          </div>

          <button onClick={() => setShowModal(true)} className="its-btn its-btn-primary" style={{ padding: '5px 12px' }}>
            <Plus size={14} />
            <span>Log Incident</span>
          </button>
        </div>
      </div>

      {incidents.length === 0 && !loading ? (
        <div style={{ flex: 1 }}>
          <TruthfulEmptyState
            title="NO INCIDENT DATA AVAILABLE"
            description="There are currently no reported, suspected, or active roadway incidents logged in the system."
            actionText="Log Verified Incident"
            actionLink="#"
            icon={<AlertTriangle size={36} />}
          />
        </div>
      ) : (
        /* 3-Column Professional Incident Workspace */
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '320px 1fr 380px',
            gap: '16px',
            flex: 1,
            overflow: 'hidden',
          }}
        >
          {/* COLUMN 1: Incident List */}
          <div
            className="its-card"
            style={{
              padding: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '10px 14px',
                borderBottom: '1px solid var(--its-border-subtle)',
                background: 'var(--its-bg-subsurface)',
                fontSize: 'var(--text-2xs)',
                fontWeight: 700,
                color: 'var(--its-text-accent)',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              Active Queue ({incidents.length})
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {incidents.map((inc) => {
                const isSelected = selectedIncident?.id === inc.id;
                return (
                  <div
                    key={inc.id}
                    onClick={() => setSelectedIncident(inc)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 'var(--radius-sm)',
                      background: isSelected ? '#eff6ff' : 'var(--its-bg-subsurface)',
                      border: `1px solid ${isSelected ? '#bfdbfe' : 'var(--its-border-subtle)'}`,
                      cursor: 'pointer',
                      transition: 'all 0.12s ease',
                      borderLeft: isSelected ? '3px solid var(--its-text-accent)' : '1px solid var(--its-border-subtle)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
                        {inc.title}
                      </span>
                      <StatusBadge status={inc.severity} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--its-text-muted)' }}>
                      <span>{inc.type}</span>
                      <span className="mono">{inc.status}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* COLUMN 2: Spatial Context & GIS Map */}
          <div
            className="its-card"
            style={{
              padding: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '10px 14px',
                borderBottom: '1px solid var(--its-border-subtle)',
                background: 'var(--its-bg-subsurface)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: 'var(--text-2xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
                <MapPin size={13} color="var(--its-text-accent)" />
                <span>SPATIAL CONTEXT: {selectedIntersection?.name || 'NETWORK OVERVIEW'}</span>
              </div>
              <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                {selectedIntersection ? `${selectedIntersection.latitude.toFixed(4)}, ${selectedIntersection.longitude.toFixed(4)}` : 'GIS SYNC'}
              </span>
            </div>

            <div style={{ flex: 1, position: 'relative' }}>
              <OperationsMap
                data={mapData}
                selectedId={selectedIntersection?.id}
                height="100%"
              />
            </div>
          </div>

          {/* COLUMN 3: Incident Details & Action Lifecycle */}
          <div
            className="its-card"
            style={{
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              overflowY: 'auto',
              gap: '14px',
            }}
          >
            {selectedIncident ? (
              <>
                <div style={{ borderBottom: '1px solid var(--its-border-subtle)', paddingBottom: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                    <span className={`status-badge ${selectedIncident.severity.toLowerCase()}`}>
                      {selectedIncident.severity} PRIORITY
                    </span>
                    <StatusBadge status={selectedIncident.status} />
                  </div>
                  <h2 style={{ fontSize: 'var(--text-md)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
                    {selectedIncident.title}
                  </h2>
                </div>

                {/* Technical Metadata */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: 'var(--text-xs)' }}>
                  <div style={{ background: 'var(--its-bg-subsurface)', padding: '8px', borderRadius: 'var(--radius-sm)' }}>
                    <div className="metric-label">INCIDENT TYPE</div>
                    <div style={{ fontWeight: 600, marginTop: '2px' }}>{selectedIncident.type}</div>
                  </div>
                  <div style={{ background: 'var(--its-bg-subsurface)', padding: '8px', borderRadius: 'var(--radius-sm)' }}>
                    <div className="metric-label">DETECTION SOURCE</div>
                    <div style={{ fontWeight: 600, marginTop: '2px' }}>{selectedIncident.source}</div>
                  </div>
                  <div style={{ background: 'var(--its-bg-subsurface)', padding: '8px', borderRadius: 'var(--radius-sm)' }}>
                    <div className="metric-label">AFFECTED LANES</div>
                    <div className="mono" style={{ fontWeight: 600, color: '#ef4444', marginTop: '2px' }}>
                      {selectedIncident.affected_lanes?.length ? `Lane(s) ${selectedIncident.affected_lanes.join(', ')}` : 'ALL APPROACHES'}
                    </div>
                  </div>
                  <div style={{ background: 'var(--its-bg-subsurface)', padding: '8px', borderRadius: 'var(--radius-sm)' }}>
                    <div className="metric-label">TIMESTAMP</div>
                    <div className="mono" style={{ fontSize: '10px', marginTop: '4px' }}>
                      {new Date(selectedIncident.detected_at).toLocaleTimeString()}
                    </div>
                  </div>
                </div>

                {/* Lifecycle Stage Stepper */}
                <div style={{ background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                  <div style={{ fontSize: 'var(--text-2xs)', fontWeight: 700, color: 'var(--its-text-accent)', textTransform: 'uppercase', marginBottom: '10px' }}>
                    Incident Lifecycle Progression
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', position: 'relative' }}>
                    {lifecycleStages.map((stage, idx) => {
                      const currentIdx = lifecycleStages.indexOf(selectedIncident.status);
                      const isPast = idx < currentIdx;
                      const isCurrent = idx === currentIdx;
                      return (
                        <div key={stage} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', zIndex: 2 }}>
                          <div
                            style={{
                              width: '18px',
                              height: '18px',
                              borderRadius: '50%',
                              background: isPast ? '#10b981' : isCurrent ? '#2563eb' : '#e2e8f0',
                              color: isPast || isCurrent ? '#ffffff' : '#94a3b8',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              boxShadow: isCurrent ? '0 0 8px rgba(37, 99, 235, 0.4)' : 'none',
                            }}
                          >
                            {isPast ? <Check size={11} /> : isCurrent ? <CircleDot size={11} /> : <span style={{ fontSize: '9px' }}>{idx + 1}</span>}
                          </div>
                          <span style={{ fontSize: '8px', fontFamily: 'var(--font-mono)', fontWeight: isCurrent ? 800 : 500, color: isCurrent ? 'var(--its-text-accent)' : 'var(--its-text-muted)', marginTop: '4px' }}>
                            {stage.slice(0, 4)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Operator Transition Controls */}
                <div style={{ background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                  <div style={{ fontSize: 'var(--text-2xs)', fontWeight: 700, color: 'var(--its-text-accent)', textTransform: 'uppercase', marginBottom: '8px' }}>
                    Execute Transition
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {selectedIncident.status === 'DETECTED' && (
                      <button
                        onClick={() => handleTransition(selectedIncident.id, 'VERIFIED')}
                        className="its-btn"
                        disabled={transitioning}
                        style={{ width: '100%', justifyContent: 'center' }}
                      >
                        <ShieldCheck size={14} color="#047857" />
                        <span>Verify Roadway Incident</span>
                      </button>
                    )}

                    {(selectedIncident.status === 'VERIFIED' || selectedIncident.status === 'ACTIVE') && (
                      <button
                        onClick={() => handleTransition(selectedIncident.id, 'MITIGATED')}
                        className="its-btn"
                        disabled={transitioning}
                        style={{ width: '100%', justifyContent: 'center' }}
                      >
                        <ShieldAlert size={14} color="#d97706" />
                        <span>Mitigate & Adjust Signal Plans</span>
                      </button>
                    )}

                    {selectedIncident.status !== 'RESOLVED' && (
                      <button
                        onClick={() => handleTransition(selectedIncident.id, 'RESOLVED')}
                        className="its-btn its-btn-primary"
                        disabled={transitioning}
                        style={{ width: '100%', justifyContent: 'center' }}
                      >
                        <CheckCircle2 size={14} />
                        <span>Resolve & Clear Scene</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* Operator Notes & Provenance */}
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--its-border-subtle)', fontSize: 'var(--text-2xs)' }}>
                  <div style={{ color: 'var(--its-text-muted)', marginBottom: '4px', fontWeight: 600 }}>OPERATOR AUDIT NOTES</div>
                  <div style={{ color: 'var(--its-text-secondary)', fontFamily: 'var(--font-mono)' }}>
                    {selectedIncident.operator_notes || 'No operator notes added yet.'}
                  </div>
                </div>

                {/* SLA clocks, append-only timeline, traceable evidence */}
                <IncidentLifecyclePanel
                  incidentId={selectedIncident.id}
                  onChanged={loadData}
                />
              </>
            ) : (
              <div style={{ padding: '24px', textAlign: 'center', color: 'var(--its-text-muted)', fontSize: 'var(--text-xs)' }}>
                Select an incident from the queue to review details and execute state transitions.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Log Incident Modal */}
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
              <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>Log Roadway Incident</h2>
              <button
                onClick={() => setShowModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Incident Description
                </label>
                <input
                  type="text"
                  className="its-input"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Multi-vehicle collision blocking eastbound lanes"
                  required
                />
              </div>

              <div className="grid-2">
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Type
                  </label>
                  <select className="its-select" value={type} onChange={(e) => setType(e.target.value)}>
                    <option value="ROAD_OBSTRUCTION">Road Obstruction</option>
                    <option value="SUDDEN_STOPPAGE">Sudden Stoppage</option>
                    <option value="LANE_BLOCKAGE">Lane Blockage</option>
                    <option value="ACCIDENT_PATTERN">Accident Pattern</option>
                    <option value="WRONG_WAY">Wrong-Way Movement</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Severity
                  </label>
                  <select className="its-select" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                    <option value="LOW">Low</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="HIGH">High</option>
                    <option value="CRITICAL">Critical</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Associated Intersection Node
                </label>
                <select
                  className="its-select"
                  value={intersectionId}
                  onChange={(e) => setIntersectionId(e.target.value)}
                >
                  {intersections.map((inter) => (
                    <option key={inter.id} value={inter.id}>
                      {inter.name} ({inter.code})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="its-btn">
                  Cancel
                </button>
                <button type="submit" className="its-btn its-btn-primary" disabled={creating}>
                  {creating ? 'Logging...' : 'Register Incident'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
