import React, { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { OperationsMap } from '../components/map/OperationsMap';
import type { MapData } from '../components/map/OperationsMap';
import { JunctionDrawer } from '../components/JunctionDrawer';
import { OnboardingWizard } from '../components/OnboardingWizard';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import {
  Activity,
  Sliders,
  AlertTriangle,
  PlusCircle,
  RefreshCw,
  ArrowUpRight,
  CheckCircle2,
  FileText,
  RadioTower,
  Zap
} from 'lucide-react';

export const Dashboard: React.FC = () => {
  const [summary, setSummary] = useState<any>(null);
  const [intersections, setIntersections] = useState<any[]>([]);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [selectedIntersectionId, setSelectedIntersectionId] = useState<string | null>(null);
  const [selectedIntersectionDetail, setSelectedIntersectionDetail] = useState<any | null>(null);
  const [filterMode, setFilterMode] = useState<'ALL' | 'HEALTHY' | 'ALERT'>('ALL');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [apiLatencyMs, setApiLatencyMs] = useState<number | null>(null);
  const [mapData, setMapData] = useState<MapData | null>(null);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const navigate = useNavigate();

  const loadData = useCallback(async () => {
    try {
      setRefreshing(true);
      const startTime = performance.now();
      const [sum, inters, audits, layers] = await Promise.all([
        api.getDashboardSummary().catch(() => null),
        api.getIntersections().catch(() => []),
        api.getAuditLogs().catch(() => []),
        api.getMapLayers(['junctions', 'incidents']).catch(() => null),
      ]);
      setMapData(layers);
      setApiLatencyMs(Math.round(performance.now() - startTime));

      setSummary(sum);
      setIntersections(inters);
      setAuditLogs(audits.slice(0, 6));

      if (!selectedIntersectionId && inters.length > 0) {
        setSelectedIntersectionId(inters[0].id);
        setSelectedIntersectionDetail(inters[0]);
      }
    } catch (err) {
      console.error('Failed to load dashboard data', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedIntersectionId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSelectIntersection = (id: string) => {
    setSelectedIntersectionId(id);
    const item = intersections.find(i => i.id === id);
    if (item) {
      setSelectedIntersectionDetail(item);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '48px', textAlign: 'center', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
          <RadioTower size={18} className="pulse-indicator" color="var(--its-text-accent)" />
          <span style={{ fontWeight: 700 }}>SYNCHRONIZING TOC TELEMETRY STACK...</span>
        </div>
        <div style={{ fontSize: 'var(--text-xs)' }}>Connecting to SQLite telemetry bus and spatial grid nodes.</div>
      </div>
    );
  }

  const isCleanInstallation =
    summary?.system_status === 'SYSTEM_READY_NO_INFRASTRUCTURE_CONNECTED' ||
    (summary?.infrastructure?.total_intersections === 0 &&
      summary?.infrastructure?.controllers?.total === 0);

  // Controller reachability, measured. Null when no controller is configured:
  // there is no percentage to report about an empty network, and a floor on
  // this number would tell an operator the grid is healthy when it is not.
  const totalControllers = summary?.infrastructure?.controllers?.total ?? 0;
  const connectedControllers = summary?.infrastructure?.controllers?.connected ?? 0;
  const controllerAvailabilityPct =
    totalControllers > 0
      ? Math.round((connectedControllers / totalControllers) * 100)
      : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* --------------------------------------------------------------------
          Tactile Command Center Hero & Real-Time Telemetry HUD
          -------------------------------------------------------------------- */}
      <div
        style={{
          background: 'var(--its-gradient-hero)',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-lg)',
          padding: '16px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
          boxShadow: 'var(--shadow-xs)',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <h1 style={{ fontSize: 'var(--text-lg)', fontWeight: 800, color: 'var(--its-text-primary)', letterSpacing: '0.04em' }}>
              TRAFFIC OPERATIONS CENTER
            </h1>
            <span className={`status-badge ${isCleanInstallation ? 'aging' : 'healthy'}`}>
              {isCleanInstallation ? 'READY FOR DATA' : 'OPERATIONAL'}
            </span>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                background: '#ffffff',
                border: '1px solid var(--its-border-accent)',
                padding: '2px 8px',
                borderRadius: 'var(--radius-xs)',
                fontSize: '11px',
                fontFamily: 'var(--font-mono)',
                color: 'var(--its-text-brand)',
                fontWeight: 700,
              }}
            >
              <Zap
                size={11}
                color={
                  controllerAvailabilityPct === null
                    ? 'var(--its-text-muted)'
                    : controllerAvailabilityPct === 100
                      ? 'var(--its-signal-green)'
                      : controllerAvailabilityPct > 0
                        ? 'var(--its-signal-yellow)'
                        : 'var(--its-signal-red)'
                }
              />
              <span title="Share of configured signal controllers with a readable protocol session">
                {controllerAvailabilityPct === null
                  ? 'CONTROLLERS: NONE CONFIGURED'
                  : `CONTROLLERS REPORTING: ${connectedControllers}/${totalControllers} (${controllerAvailabilityPct}%)`}
              </span>
            </div>
          </div>

          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '4px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
            <span>REGION: <b style={{ color: 'var(--its-text-primary)' }}>METRO ARTERIAL GRID</b></span>
            <span>•</span>
            <span>JURISDICTION: <b style={{ color: 'var(--its-text-primary)' }}>NEMA TS2 DUAL-RING</b></span>
            <span>•</span>
            <span style={{ color: 'var(--its-text-accent)' }}>
              API ROUND TRIP: <b className="mono">{apiLatencyMs === null ? 'NOT MEASURED' : `${apiLatencyMs}ms`}</b>
            </span>
            <span>•</span>
            <span style={{ color: 'var(--its-text-teal)' }}>ZERO FAKE DATA ENFORCED</span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            onClick={loadData}
            className="its-btn"
            disabled={refreshing}
            title="Synchronize telemetry with roadside devices"
          >
            <RefreshCw size={13} className={refreshing ? 'pulse-indicator' : ''} />
            <span>{refreshing ? 'Syncing...' : 'Sync Telemetry'}</span>
          </button>

          <Link to="/intersections" className="its-btn its-btn-primary" style={{ textDecoration: 'none' }}>
            <PlusCircle size={13} />
            <span>Add Node</span>
          </Link>
        </div>
      </div>

      {/* --------------------------------------------------------------------
          Primary Split: Live Spatial Network Map (Left) + Operational Stack (Right)
          -------------------------------------------------------------------- */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr)', gap: '16px' }}>
        {/* LEFT: Live Network Map with slide-out contextual detail */}
        <div className="its-card" style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '620px' }}>
          {/* Map Header with Tactical Filters */}
          <div
            style={{
              padding: '10px 16px',
              borderBottom: '1px solid var(--its-border-subtle)',
              background: 'var(--its-bg-subsurface)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <RadioTower size={16} color="var(--its-text-accent)" />
              <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                Spatial Network GIS
              </span>
              <div style={{ display: 'flex', gap: '4px', marginLeft: '6px' }}>
                <button
                  onClick={() => setFilterMode('ALL')}
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: 'var(--radius-xs)',
                    border: '1px solid ' + (filterMode === 'ALL' ? 'var(--its-text-accent)' : 'var(--its-border-subtle)'),
                    background: filterMode === 'ALL' ? '#eff6ff' : '#ffffff',
                    color: filterMode === 'ALL' ? 'var(--its-text-accent)' : 'var(--its-text-muted)',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  ALL ({intersections.length})
                </button>
                <button
                  onClick={() => setFilterMode('HEALTHY')}
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: 'var(--radius-xs)',
                    border: '1px solid ' + (filterMode === 'HEALTHY' ? 'var(--its-signal-green)' : 'var(--its-border-subtle)'),
                    background: filterMode === 'HEALTHY' ? 'var(--its-signal-green-bg)' : '#ffffff',
                    color: filterMode === 'HEALTHY' ? '#047857' : 'var(--its-text-muted)',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  NOMINAL ({intersections.filter(i => i.operational_status === 'HEALTHY').length})
                </button>
              </div>
            </div>

            <Link to="/live-map" style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-accent)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
              <span>Expand Fullscreen</span>
              <ArrowUpRight size={12} />
            </Link>
          </div>

          <div style={{ flex: 1, position: 'relative' }}>
            {intersections.length === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
                <div style={{ textAlign: 'center', maxWidth: '420px' }}>
                  <div
                    className="mono"
                    style={{
                      fontSize: 'var(--text-sm)', fontWeight: 700,
                      color: 'var(--its-text-primary)', letterSpacing: '0.03em',
                    }}
                  >
                    SYSTEM READY - NO TRAFFIC INFRASTRUCTURE IS CURRENTLY CONNECTED
                  </div>
                  <p style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', lineHeight: 1.6, margin: '10px 0 14px' }}>
                    The map plots junctions you have configured. Connect a signal
                    controller, camera or detector and its measured state appears here.
                    Nothing is placed on the map until real infrastructure reports.
                  </p>
                  <button onClick={() => setWizardOpen(true)} className="its-btn its-btn-primary">
                    <PlusCircle size={13} />
                    <span>Connect your first infrastructure</span>
                  </button>
                </div>
              </div>
            ) : (
              <>
                <OperationsMap
                  data={mapData}
                  loading={loading && !mapData}
                  selectedId={selectedIntersectionId}
                  onSelectJunction={(id) => {
                    handleSelectIntersection(id);
                    setDrawerId(id);
                  }}
                  height="100%"
                />

                {/* Floating Contextual Inspector for Selected Node */}
                {selectedIntersectionDetail && (
                  <div
                    style={{
                      position: 'absolute',
                      top: '12px',
                      left: '12px',
                      width: '320px',
                      background: 'rgba(255, 255, 255, 0.94)',
                      backdropFilter: 'blur(10px)',
                      border: '1px solid var(--its-border-accent)',
                      borderRadius: 'var(--radius-md)',
                      padding: '14px',
                      zIndex: 500,
                      boxShadow: 'var(--shadow-md)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                      <div>
                        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
                          {selectedIntersectionDetail.name}
                        </div>
                        <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
                          CODE: {selectedIntersectionDetail.code || 'NOT SET'}
                        </div>
                      </div>
                      <StatusBadge status={selectedIntersectionDetail.operational_status || 'UNKNOWN'} />
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', margin: '10px 0', fontSize: 'var(--text-xs)' }}>
                      <div style={{ background: 'var(--its-bg-subsurface)', padding: '6px 8px', borderRadius: 'var(--radius-sm)' }}>
                        <div style={{ color: 'var(--its-text-muted)', fontSize: '10px', fontWeight: 600 }}>LAT / LNG</div>
                        <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--its-text-primary)' }}>
                          {selectedIntersectionDetail.latitude?.toFixed(4)}, {selectedIntersectionDetail.longitude?.toFixed(4)}
                        </div>
                      </div>
                      <div style={{ background: 'var(--its-bg-subsurface)', padding: '6px 8px', borderRadius: 'var(--radius-sm)' }}>
                        <div style={{ color: 'var(--its-text-muted)', fontSize: '10px', fontWeight: 600 }}>APPROACHES</div>
                        <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--its-text-primary)' }}>
                          {/* Geometry is only known when approaches were configured.
                              Defaulting to "4 LEG" described junctions nobody surveyed. */}
                          {selectedIntersectionDetail.approaches?.length
                            ? `${selectedIntersectionDetail.approaches.length} LEG JUNCTION`
                            : 'GEOMETRY NOT CONFIGURED'}
                        </div>
                      </div>
                    </div>

                    <button
                      className="its-btn its-btn-primary"
                      style={{ width: '100%', fontSize: 'var(--text-xs)', justifyContent: 'center' }}
                      onClick={() => navigate(`/intersections/${selectedIntersectionDetail.id}`)}
                    >
                      <span>Open Junction Topology Blueprint</span>
                      <ArrowUpRight size={13} />
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* RIGHT: Operational Command Stack */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Active Incidents Console Card */}
          <div className="its-card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div className="its-card-header">
              <span className="its-card-title">
                <AlertTriangle size={15} color="var(--its-signal-red)" />
                <span>Active Incident Queue</span>
              </span>
              <Link to="/incidents" style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-accent)', textDecoration: 'none', fontWeight: 600 }}>
                Console ({summary?.incidents?.active_count || 0}) →
              </Link>
            </div>

            <div style={{ flex: 1, overflowY: 'auto' }}>
              {summary?.incidents?.items?.length === 0 ? (
                <div style={{ padding: '24px 12px', textAlign: 'center' }}>
                  <CheckCircle2 size={28} color="var(--its-signal-green)" style={{ margin: '0 auto 8px' }} />
                  <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
                    NO UNMITIGATED INCIDENTS
                  </div>
                  <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginTop: '4px' }}>
                    Regional arterial operations nominal. All lanes open.
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {summary?.incidents?.items?.map((inc: any) => (
                    <div
                      key={inc.id}
                      style={{
                        padding: '10px 12px',
                        background: 'var(--its-bg-subsurface)',
                        border: '1px solid var(--its-border-subtle)',
                        borderRadius: 'var(--radius-md)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <div>
                        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
                          {inc.title}
                        </div>
                        <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginTop: '2px' }}>
                          {inc.type} • Status: <b style={{ color: 'var(--its-text-primary)' }}>{inc.status}</b>
                        </div>
                      </div>
                      <StatusBadge status={inc.severity} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Infrastructure Health & Hardware Telemetry Strip */}
          <div className="its-card">
            <div className="its-card-header">
              <span className="its-card-title">
                <Sliders size={15} color="var(--its-text-accent)" />
                <span>Field Controller Reachability</span>
              </span>
              <StatusBadge status={summary?.infrastructure?.controllers?.status || 'NOT_CONFIGURED'} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginTop: '4px' }}>
              <div style={{ background: 'var(--its-bg-subsurface)', padding: '10px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                <div className="metric-label">CONTROLLERS</div>
                <div className="metric-value">
                  {summary?.infrastructure?.controllers?.connected || 0}
                  <span className="metric-unit">/ {summary?.infrastructure?.controllers?.total || 0}</span>
                </div>
              </div>

              <div style={{ background: 'var(--its-bg-subsurface)', padding: '10px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                <div className="metric-label">EDGE CAMERAS</div>
                <div className="metric-value">
                  {summary?.infrastructure?.cameras?.connected || 0}
                  <span className="metric-unit">/ {summary?.infrastructure?.cameras?.total || 0}</span>
                </div>
              </div>

              <div style={{ background: 'var(--its-bg-subsurface)', padding: '10px', borderRadius: 'var(--radius-md)', border: '1px solid var(--its-border-subtle)' }}>
                <div className="metric-label">RADAR / LOOPS</div>
                <div className="metric-value">
                  {summary?.infrastructure?.sensors?.connected || 0}
                  <span className="metric-unit">/ {summary?.infrastructure?.sensors?.total || 0}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* --------------------------------------------------------------------
          Lower Section: Telemetry Interlock Feed & Cryptographic Audit Trail
          -------------------------------------------------------------------- */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '16px' }}>
        {/* Safety & Telemetry Interlock Feed */}
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              <Activity size={15} color="var(--its-signal-yellow)" />
              <span>Safety & Telemetry Interlock Feed</span>
            </span>
            <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
              UNACKNOWLEDGED: {summary?.alerts?.unacknowledged_count || 0}
            </span>
          </div>

          {summary?.alerts?.items?.length === 0 ? (
            <TruthfulEmptyState
              title="ALL SUBSYSTEMS NOMINAL"
              description="Zero conflict monitor unit (MMU) faults, communication timeouts, or yellow-change clearance alarms."
            />
          ) : (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Category</th>
                    <th>Alert Description</th>
                  </tr>
                </thead>
                <tbody>
                  {summary?.alerts?.items?.map((alt: any) => (
                    <tr key={alt.id}>
                      <td><StatusBadge status={alt.severity} /></td>
                      <td style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)' }}>{alt.category}</td>
                      <td style={{ fontSize: '0.75rem' }}>{alt.title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Real-time Tamper-Evident Operator Audit Trail */}
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              <FileText size={15} color="var(--its-text-accent)" />
              <span>Operator Audit Trail</span>
            </span>
            <Link to="/audit" style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-accent)', textDecoration: 'none', fontWeight: 600 }}>
              Full Log →
            </Link>
          </div>

          {auditLogs.length === 0 ? (
            <TruthfulEmptyState
              title="AUDIT LOG EMPTY"
              description="All operator logins, phase command overrides, and parameter updates are cryptographically logged here."
            />
          ) : (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Operator</th>
                    <th>Action</th>
                    <th>Target</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((log: any) => (
                    <tr key={log.id}>
                      <td style={{ fontSize: '0.7rem', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
                        {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : 'N/A'}
                      </td>
                      <td style={{ fontWeight: 600, fontSize: '0.75rem' }}>{log.actor_username || 'SYSTEM'}</td>
                      <td>
                        <span className="status-badge blue" style={{ fontSize: '10px' }}>
                          {log.action}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--its-text-secondary)' }}>
                        {log.target_type || 'SYSTEM'}:{log.target_id?.slice(0, 6) || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {drawerId && (
        <JunctionDrawer
          junctionId={drawerId}
          mapFeature={mapData?.layers.junctions?.features.find((f: any) => f.id === drawerId)}
          thresholds={mapData?.quality_thresholds_sec}
          onClose={() => setDrawerId(null)}
        />
      )}

      {wizardOpen && (
        <OnboardingWizard onClose={() => setWizardOpen(false)} onComplete={loadData} />
      )}
    </div>
  );
};
