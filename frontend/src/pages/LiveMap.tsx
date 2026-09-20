import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { GisMap } from '../components/GisMap';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import {
  ArrowUpRight,
  RefreshCw,
  GitCommit
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';

export const LiveMap: React.FC = () => {
  const [intersections, setIntersections] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedTraffic, setSelectedTraffic] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const navigate = useNavigate();

  const loadData = useCallback(async () => {
    try {
      setRefreshing(true);
      const data = await api.getIntersections();
      setIntersections(data);
      if (data.length > 0 && !selectedId) {
        setSelectedId(data[0].id);
      }
    } catch (err) {
      console.error('Failed to load map intersections', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedTraffic(null);
      return;
    }
    const loadTraffic = async () => {
      try {
        const traffic = await api.getIntersectionTraffic(selectedId);
        setSelectedTraffic(traffic);
      } catch {
        setSelectedTraffic(null);
      }
    };
    loadTraffic();
  }, [selectedId]);

  const selectedIntersection = intersections.find((i) => i.id === selectedId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', height: 'calc(100vh - 120px)' }}>
      {/* Top Bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'var(--its-gradient-hero)',
          padding: '12px 20px',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--its-border-subtle)',
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: 'var(--text-md)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
              LIVE GIS OPERATIONS MAP
            </h1>
            <span className="status-badge active">ESRI DOT CANVAS</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            High-contrast light arterial GIS basemap displaying real NEMA TS2 junction nodes and detector reachability.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            onClick={loadData}
            className="its-btn"
            disabled={refreshing}
            title="Refresh GIS spatial nodes"
          >
            <RefreshCw size={13} className={refreshing ? 'pulse-indicator' : ''} />
            <span>Sync GIS</span>
          </button>

          <Link to="/intersections" className="its-btn its-btn-primary" style={{ textDecoration: 'none' }}>
            <GitCommit size={13} />
            <span>Add Node</span>
          </Link>
        </div>
      </div>

      {intersections.length === 0 && !loading ? (
        <div style={{ flex: 1 }}>
          <TruthfulEmptyState
            title="NO GIS INFRASTRUCTURE CONFIGURED"
            description="No physical intersections with geographic coordinates (latitude/longitude) have been configured in the system."
            actionText="Add Intersection Coordinates"
            actionLink="/intersections"
          />
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 380px', gap: '16px', flex: 1, overflow: 'hidden' }}>
          {/* Main Map Canvas */}
          <div
            className="its-card"
            style={{
              padding: 0,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              position: 'relative',
            }}
          >
            <GisMap
              intersections={intersections}
              selectedId={selectedId}
              onSelectIntersection={(id) => setSelectedId(id)}
              height="100%"
            />
          </div>

          {/* Right Inspector Drawer (Section 18) */}
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
                padding: '14px 16px',
                borderBottom: '1px solid var(--its-border-subtle)',
                background: 'var(--its-bg-subsurface)',
              }}
            >
              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-cyan)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                SPATIAL NODE INSPECTOR
              </div>
              <div style={{ fontSize: 'var(--text-md)', fontWeight: 800, color: 'var(--its-text-primary)', marginTop: '2px' }}>
                {selectedIntersection ? selectedIntersection.name : 'Select node on GIS map'}
              </div>
              {selectedIntersection && (
                <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                  CODE: {selectedIntersection.code} • {selectedIntersection.latitude.toFixed(5)}, {selectedIntersection.longitude.toFixed(5)}
                </div>
              )}
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {selectedIntersection ? (
                <>
                  {/* Status Grid */}
                  <div>
                    <div style={{ fontSize: 'var(--text-2xs)', fontWeight: 700, color: 'var(--its-text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>
                      SUBSYSTEM STATUS
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)' }}>Operational Health:</span>
                        <StatusBadge status={selectedIntersection.operational_status} />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)' }}>Signal Controller:</span>
                        <StatusBadge status={selectedIntersection.controller_status} />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)' }}>Edge Camera:</span>
                        <StatusBadge status={selectedIntersection.camera_status} />
                      </div>
                    </div>
                  </div>

                  {/* Telemetry Observations */}
                  <div>
                    <div style={{ fontSize: 'var(--text-2xs)', fontWeight: 700, color: 'var(--its-text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>
                      ROADWAY TELEMETRY
                    </div>
                    {selectedTraffic && selectedTraffic.data_quality !== 'NO_DATA' && selectedTraffic.vehicle_count !== null ? (
                      <div
                        style={{
                          background: 'var(--its-bg-subsurface)',
                          padding: '12px',
                          borderRadius: 'var(--radius-md)',
                          border: '1px solid var(--its-border-subtle)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '8px',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>Flow Rate:</span>
                          <span className="mono" style={{ fontWeight: 700 }}>{selectedTraffic.vehicle_count} veh/hr</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>Mean Speed:</span>
                          <span className="mono" style={{ fontWeight: 700 }}>{selectedTraffic.avg_speed_kph} km/h</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>Queue Depth:</span>
                          <span className="mono" style={{ fontWeight: 700 }}>{selectedTraffic.queue_length_meters} m</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '8px', borderTop: '1px solid var(--its-border-subtle)' }}>
                          <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}>Freshness:</span>
                          <StatusBadge status={selectedTraffic.data_quality} />
                        </div>
                      </div>
                    ) : (
                      <div
                        style={{
                          padding: '16px',
                          background: 'var(--its-bg-subsurface)',
                          border: '1px dashed var(--its-border-subtle)',
                          borderRadius: 'var(--radius-md)',
                          fontSize: 'var(--text-xs)',
                          color: 'var(--its-text-muted)',
                          textAlign: 'center',
                        }}
                      >
                        NO LIVE TELEMETRY
                        <div style={{ fontSize: '10px', marginTop: '4px' }}>
                          Roadside sensors not reporting counts.
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div style={{ marginTop: 'auto' }}>
                    <button
                      onClick={() => navigate(`/intersections/${selectedIntersection.id}`)}
                      className="its-btn its-btn-primary"
                      style={{ width: '100%', justifyContent: 'space-between', padding: '9px 14px' }}
                    >
                      <span>Open Junction Topology</span>
                      <ArrowUpRight size={14} />
                    </button>
                  </div>
                </>
              ) : (
                <div style={{ color: 'var(--its-text-muted)', fontSize: 'var(--text-xs)', textAlign: 'center', marginTop: '40px' }}>
                  Click an intersection pin on the GIS map to inspect live controllers and telemetry.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
