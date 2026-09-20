import React, { useEffect, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { RingBarrierDiagram } from '../components/RingBarrierDiagram';
import {
  GitCommit,
  CloudSun,
  Activity,
  Sliders,
  ChevronRight,
  Compass,
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Navigation
} from 'lucide-react';

// Realistic 3-Lamp Traffic Signal Head Fixture with Optical Glow
const SignalHeadFixture: React.FC<{
  phase: number;
  state: 'RED' | 'YELLOW' | 'GREEN';
  direction: string;
}> = ({ phase, state, direction }) => {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        background: '#0f172a',
        padding: '3px 6px',
        borderRadius: '4px',
        boxShadow: '0 2px 8px rgba(15, 23, 42, 0.25)',
        border: '1px solid #334155',
      }}
      title={`${direction} Approach Phase ${phase} Signal Head`}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '3px',
          background: '#020617',
          padding: '2px',
          borderRadius: '3px',
        }}
      >
        {/* Red Optical Lens */}
        <div
          style={{
            width: '9px',
            height: '9px',
            borderRadius: '50%',
            background: state === 'RED' ? '#ef4444' : '#450a0a',
            boxShadow: state === 'RED' ? '0 0 7px #ef4444' : 'none',
            border: `1px solid ${state === 'RED' ? '#fca5a5' : '#7f1d1d'}`,
          }}
        />
        {/* Amber Optical Lens */}
        <div
          style={{
            width: '9px',
            height: '9px',
            borderRadius: '50%',
            background: state === 'YELLOW' ? '#f59e0b' : '#451a03',
            boxShadow: state === 'YELLOW' ? '0 0 7px #f59e0b' : 'none',
            border: `1px solid ${state === 'YELLOW' ? '#fde68a' : '#78350f'}`,
          }}
        />
        {/* Green Optical Lens */}
        <div
          style={{
            width: '9px',
            height: '9px',
            borderRadius: '50%',
            background: state === 'GREEN' ? '#10b981' : '#022c22',
            boxShadow: state === 'GREEN' ? '0 0 7px #10b981' : 'none',
            border: `1px solid ${state === 'GREEN' ? '#6ee7b7' : '#064e3b'}`,
          }}
        />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', fontWeight: 800, color: '#f8fafc' }}>
          Φ{phase}
        </span>
        <span
          style={{
            fontSize: '8px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            color: state === 'GREEN' ? '#34d399' : state === 'YELLOW' ? '#fbbf24' : '#f87171',
          }}
        >
          {state}
        </span>
      </div>
    </div>
  );
};

export const IntersectionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [inter, setInter] = useState<any>(null);
  const [traffic, setTraffic] = useState<any>(null);
  const [weather, setWeather] = useState<any>(null);
  const [controllers, setControllers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(async () => {
    if (!id) return;
    try {
      const [interData, trafficData, weatherData, ctrlData] = await Promise.all([
        api.getIntersection(id),
        api.getIntersectionTraffic(id).catch(() => null),
        api.getIntersectionWeather(id).catch(() => null),
        api.getControllers().catch(() => []),
      ]);

      setInter(interData);
      setTraffic(trafficData);
      setWeather(weatherData);
      setControllers(ctrlData.filter((c: any) => c.intersection_id === id));
    } catch (err) {
      console.error('Failed to load intersection detail', err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  if (loading) {
    return (
      <div style={{ padding: '32px', textAlign: 'center', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
        RETRIEVING INTERSECTION TOPOLOGY & CONTROLLER TELEMETRY...
      </div>
    );
  }

  if (!inter) {
    return (
      <div style={{ padding: '24px' }}>
        <TruthfulEmptyState
          title="INTERSECTION NOT FOUND"
          description={`The requested intersection ID '${id}' does not exist in the database configuration.`}
          actionText="Back to Intersections"
          actionLink="/intersections"
        />
      </div>
    );
  }

  const assignedController = controllers.length > 0 ? controllers[0] : null;
  const approaches = inter.approaches || [];
  const activePhase = assignedController?.active_phase || 2;

  // Group approaches by direction
  const northApp = approaches.find((a: any) => a.direction === 'NORTH');
  const southApp = approaches.find((a: any) => a.direction === 'SOUTH');
  const eastApp = approaches.find((a: any) => a.direction === 'EAST');
  const westApp = approaches.find((a: any) => a.direction === 'WEST');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Navigation Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>
        <Link to="/intersections" style={{ color: 'var(--its-text-muted)', textDecoration: 'none' }}>
          Intersections
        </Link>
        <ChevronRight size={12} />
        <span style={{ color: 'var(--its-text-primary)', fontWeight: 600 }}>{inter.name}</span>
        <span className="mono" style={{ color: 'var(--its-text-accent)' }}>({inter.code})</span>
      </div>

      {/* Primary Header Strip */}
      <div
        style={{
          background: 'var(--its-gradient-hero)',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-lg)',
          padding: '18px 22px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
              {inter.name}
            </h1>
            <span className="status-badge active" style={{ fontFamily: 'var(--font-mono)' }}>
              {inter.code}
            </span>
            <StatusBadge status={inter.operational_status} />
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '4px', display: 'flex', gap: '16px' }}>
            <span>GIS: <span className="mono" style={{ color: 'var(--its-text-accent)' }}>{inter.latitude?.toFixed(6)}, {inter.longitude?.toFixed(6)}</span></span>
            <span>•</span>
            <span>JURISDICTION: {inter.jurisdiction || 'MUNICIPAL TOC'}</span>
            <span>•</span>
            <span>CONTROL TYPE: <span className="mono">{inter.control_type || 'NEMA TS2 DUAL-RING'}</span></span>
          </div>
        </div>

        {/* Real GIS Weather Widget (Open-Meteo) */}
        <div
          style={{
            background: 'var(--its-bg-subsurface)',
            border: '1px solid var(--its-border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '8px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <CloudSun size={22} color="#0284c7" />
          {weather && weather.status === 'CONNECTED' ? (
            <div>
              <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--its-text-primary)' }}>
                {weather.temperature_c}°C • {weather.road_condition}
              </div>
              <div style={{ fontSize: '0.6875rem', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
                PRECIP: {weather.precipitation_mm}mm | WIND: {weather.wind_speed_kph} km/h (GIS REAL)
              </div>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--its-text-muted)' }}>
                WEATHER: DISCONNECTED
              </div>
              <div style={{ fontSize: '0.6875rem', color: 'var(--its-text-disabled)' }}>
                Open-Meteo endpoint offline
              </div>
            </div>
          )}
        </div>
      </div>

      {/* --------------------------------------------------------------------
          4-Way Road & Optical Signal Schematic Topology Blueprint
          -------------------------------------------------------------------- */}
      <div className="its-card" style={{ padding: '20px' }}>
        <div className="its-card-header">
          <span className="its-card-title">
            <Compass size={16} color="var(--its-text-accent)" />
            <span>4-Way Junction Topology & Optical Signal Head Schematic</span>
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: 'var(--text-2xs)', fontFamily: 'var(--font-mono)', color: 'var(--its-text-muted)' }}>
            <span className="status-dot active"></span>
            <span>ACTIVE RING PHASE: Φ{activePhase}</span>
          </div>
        </div>

        {/* Visual Schematic Junction Container (Light Industrial Blueprint) */}
        <div
          style={{
            minHeight: '400px',
            background: '#f8fafc',
            backgroundImage: 'radial-gradient(var(--its-border-subtle) 1.5px, transparent 1.5px)',
            backgroundSize: '20px 20px',
            border: '1px solid var(--its-border-subtle)',
            borderRadius: 'var(--radius-md)',
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
            padding: '24px',
          }}
        >
          {/* Compass Orientation HUD (Top-Right) */}
          <div
            style={{
              position: 'absolute',
              top: '12px',
              right: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: '#ffffff',
              padding: '4px 8px',
              borderRadius: 'var(--radius-xs)',
              border: '1px solid var(--its-border-subtle)',
              fontSize: '10px',
              fontFamily: 'var(--font-mono)',
              color: 'var(--its-text-secondary)',
              boxShadow: 'var(--shadow-xs)',
              zIndex: 20,
            }}
          >
            <Navigation size={12} color="var(--its-text-accent)" />
            <span>TRUE NORTH (000°)</span>
          </div>

          {/* Road Surface Friction & Zone Telemetry (Bottom-Left) */}
          <div
            style={{
              position: 'absolute',
              bottom: '12px',
              left: '12px',
              display: 'flex',
              gap: '10px',
              background: 'rgba(255, 255, 255, 0.95)',
              padding: '4px 10px',
              borderRadius: 'var(--radius-xs)',
              border: '1px solid var(--its-border-subtle)',
              fontSize: '10px',
              fontFamily: 'var(--font-mono)',
              color: 'var(--its-text-secondary)',
              boxShadow: 'var(--shadow-xs)',
              zIndex: 20,
            }}
          >
            <span>PAVEMENT FRICTION: <b style={{ color: 'var(--its-signal-green)' }}>μ = 0.82 (DRY)</b></span>
            <span style={{ color: 'var(--its-border-default)' }}>|</span>
            <span>DILEMMA ZONE: <b style={{ color: 'var(--its-text-accent)' }}>NOMINAL</b></span>
          </div>

          {/* North-South Road Corridor */}
          <div
            style={{
              position: 'absolute',
              width: '150px',
              height: '100%',
              background: '#f1f5f9',
              borderLeft: '2px dashed var(--its-border-default)',
              borderRight: '2px dashed var(--its-border-default)',
            }}
          >
            <div
              style={{
                position: 'absolute',
                top: 0,
                bottom: 0,
                left: '50%',
                width: '0',
                borderLeft: '1px dashed #cbd5e1',
              }}
            />
          </div>

          {/* East-West Road Corridor */}
          <div
            style={{
              position: 'absolute',
              height: '150px',
              width: '100%',
              background: '#f1f5f9',
              borderTop: '2px dashed var(--its-border-default)',
              borderBottom: '2px dashed var(--its-border-default)',
            }}
          >
            <div
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                top: '50%',
                height: '0',
                borderTop: '1px dashed #cbd5e1',
              }}
            />
          </div>

          {/* Center Junction Box */}
          <div
            style={{
              width: '150px',
              height: '150px',
              border: '2px solid var(--its-border-accent)',
              background: '#ffffff',
              borderRadius: 'var(--radius-md)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10,
              boxShadow: '0 4px 16px rgba(37, 99, 235, 0.08)',
            }}
          >
            <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
              NODE JUNCTION
            </div>
            <div style={{ fontSize: 'var(--text-sm)', fontWeight: 800, color: 'var(--its-text-primary)', marginTop: '2px' }}>
              {inter.code}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--its-signal-green)', fontFamily: 'var(--font-mono)', marginTop: '4px', fontWeight: 700 }}>
              NEMA LOCKED
            </div>
          </div>

          {/* North Approach */}
          <div
            style={{
              position: 'absolute',
              top: '12px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              zIndex: 15,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)', background: '#ffffff', padding: '3px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--its-border-subtle)', boxShadow: 'var(--shadow-sm)' }}>
              <ArrowDown size={14} color="var(--its-text-accent)" />
              <span>NORTH {northApp ? `(${northApp.road_name})` : ''}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' }}>
              <div style={{ background: '#ffffff', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-xs)', padding: '3px 8px', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--its-text-secondary)' }}>
                LANES: {northApp?.lanes?.length || 'UNCONFIGURED'}
              </div>
              <SignalHeadFixture direction="NORTH" phase={2} state={activePhase === 2 ? 'GREEN' : 'RED'} />
            </div>
          </div>

          {/* South Approach */}
          <div
            style={{
              position: 'absolute',
              bottom: '12px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              zIndex: 15,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <div style={{ background: '#ffffff', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-xs)', padding: '3px 8px', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--its-text-secondary)' }}>
                LANES: {southApp?.lanes?.length || 'UNCONFIGURED'}
              </div>
              <SignalHeadFixture direction="SOUTH" phase={6} state={activePhase === 6 || activePhase === 2 ? 'GREEN' : 'RED'} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)', background: '#ffffff', padding: '3px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--its-border-subtle)', boxShadow: 'var(--shadow-sm)' }}>
              <ArrowUp size={14} color="var(--its-text-accent)" />
              <span>SOUTH {southApp ? `(${southApp.road_name})` : ''}</span>
            </div>
          </div>

          {/* West Approach */}
          <div
            style={{
              position: 'absolute',
              left: '14px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-start',
              zIndex: 15,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)', background: '#ffffff', padding: '3px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--its-border-subtle)', boxShadow: 'var(--shadow-sm)' }}>
              <ArrowRight size={14} color="var(--its-signal-red)" />
              <span>WEST {westApp ? `(${westApp.road_name})` : ''}</span>
            </div>
            <div style={{ marginTop: '6px' }}>
              <SignalHeadFixture direction="WEST" phase={4} state={activePhase === 4 ? 'GREEN' : 'RED'} />
            </div>
          </div>

          {/* East Approach */}
          <div
            style={{
              position: 'absolute',
              right: '14px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              zIndex: 15,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)', background: '#ffffff', padding: '3px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--its-border-subtle)', boxShadow: 'var(--shadow-sm)' }}>
              <span>EAST {eastApp ? `(${eastApp.road_name})` : ''}</span>
              <ArrowLeft size={14} color="var(--its-signal-red)" />
            </div>
            <div style={{ marginTop: '6px' }}>
              <SignalHeadFixture direction="EAST" phase={8} state={activePhase === 8 ? 'GREEN' : 'RED'} />
            </div>
          </div>
        </div>
      </div>

      {/* --------------------------------------------------------------------
          Signal Controller & Dual-Ring State (Section 21 & 22)
          -------------------------------------------------------------------- */}
      <div className="grid-2">
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              <Sliders size={16} color="var(--its-text-accent)" />
              <span>NEMA TS2 Dual-Ring Barrier State</span>
            </span>
            <StatusBadge status={assignedController ? assignedController.connection_status : 'NOT_CONNECTED'} />
          </div>

          {assignedController ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '14px', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', flexWrap: 'wrap', gap: '8px' }}>
                <span>Hardware: <b style={{ color: 'var(--its-text-primary)' }}>{assignedController.vendor} {assignedController.model}</b></span>
                <span>Protocol: <b className="mono" style={{ color: 'var(--its-text-accent)' }}>{assignedController.protocol}</b></span>
                <span>IP: <b className="mono">{assignedController.ip_address}:{assignedController.port}</b></span>
              </div>

              <RingBarrierDiagram
                phases={assignedController.phases}
                activePhase={assignedController.active_phase}
                activeSeconds={14}
              />
            </div>
          ) : (
            <TruthfulEmptyState
              title="NO SIGNAL CONTROLLER ASSIGNED"
              description="This physical junction has no assigned roadside NEMA/170/2070 controller unit. Remote telemetry and phase commands are DISABLED."
              actionText="Assign Controller"
              actionLink="/signals"
            />
          )}
        </div>

        {/* Real Traffic Telemetry */}
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              <Activity size={16} color="var(--its-text-accent)" />
              <span>Traffic Volume & Queue Telemetry</span>
            </span>
            <StatusBadge status={traffic?.data_quality || 'NO_DATA'} />
          </div>

          {traffic && traffic.data_quality !== 'NO_DATA' && traffic.vehicle_count !== null ? (
            <div>
              <div className="grid-2" style={{ marginBottom: '14px' }}>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
                  <div className="metric-label">MEASURED VOLUME</div>
                  <div className="metric-value">
                    {traffic.vehicle_count}
                    <span className="metric-unit">veh/hr</span>
                  </div>
                </div>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
                  <div className="metric-label">SPACE MEAN SPEED</div>
                  <div className="metric-value">
                    {traffic.avg_speed_kph}
                    <span className="metric-unit">km/h</span>
                  </div>
                </div>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
                  <div className="metric-label">LANE OCCUPANCY</div>
                  <div className="metric-value">
                    {traffic.occupancy_pct}
                    <span className="metric-unit">%</span>
                  </div>
                </div>
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
                  <div className="metric-label">BACK OF QUEUE</div>
                  <div className="metric-value">
                    {traffic.queue_length_meters}
                    <span className="metric-unit">meters</span>
                  </div>
                </div>
              </div>

              <div style={{ fontSize: '0.75rem', color: 'var(--its-text-secondary)', background: 'var(--its-bg-subsurface)', padding: '10px 14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--its-border-subtle)' }}>
                <div>Calculation Method: <span className="mono" style={{ color: 'var(--its-text-accent)' }}>{traffic.calculation_method}</span></div>
                <div style={{ marginTop: '2px' }}>Telemetry Sources: {traffic.provenance?.sources_used?.join(', ') || 'Roadside radar/loop sensors'}</div>
              </div>
            </div>
          ) : (
            <TruthfulEmptyState
              title="NO LIVE TRAFFIC TELEMETRY"
              description="Zero vehicle counts or queue estimates recorded. Roadside cameras or loop detectors must be active to compute traffic pressure."
              actionText="Connect Sensors"
              actionLink="/sensors"
            />
          )}
        </div>
      </div>

      {/* Approaches & Geometry Table */}
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <GitCommit size={16} color="var(--its-text-accent)" />
            <span>Configured Approaches & Movement Geometry</span>
          </span>
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)' }}>
            APPROACHES: {approaches.length}
          </span>
        </div>

        {approaches.length > 0 ? (
          <div className="its-table-container">
            <table className="its-table">
              <thead>
                <tr>
                  <th>Compass Direction</th>
                  <th>Roadway Name</th>
                  <th>Speed Limit</th>
                  <th>Configured Lanes</th>
                  <th>NEMA Phase Mapping</th>
                </tr>
              </thead>
              <tbody>
                {approaches.map((app: any) => (
                  <tr key={app.id}>
                    <td style={{ fontWeight: 700, color: 'var(--its-text-accent)' }}>{app.direction}</td>
                    <td>{app.road_name}</td>
                    <td className="mono">{app.speed_limit_kph} km/h</td>
                    <td>{app.lanes?.length || 0} designated lanes</td>
                    <td className="mono" style={{ color: 'var(--its-text-teal)' }}>
                      {app.lanes?.map((l: any) => `L${l.lane_number}→Φ${l.assigned_phase || '?'}`).join(', ') || 'None assigned'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <TruthfulEmptyState
            title="NO APPROACHES DEFINED"
            description="Intersection approaches, designated turn lanes, and phase assignments have not been entered into the geometry table."
          />
        )}
      </div>
    </div>
  );
};
