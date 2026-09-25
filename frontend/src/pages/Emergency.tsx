import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { Siren, RefreshCw } from 'lucide-react';
import { PreemptionVerdict } from '../components/emergency/PreemptionVerdict';

export const Emergency: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [intersections, setIntersections] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Preemption Test Dispatch
  const [vehicleId, setVehicleId] = useState('');
  const [vehicleType, setVehicleType] = useState('AMBULANCE');
  const [intersectionId, setIntersectionId] = useState('');
  const [targetPhase, setTargetPhase] = useState(2);
  const [submitting, setSubmitting] = useState(false);
  const [lastVerdict, setLastVerdict] = useState<any>(null);

  const loadData = useCallback(async () => {
    try {
      const [emRes, inters] = await Promise.all([
        api.getEmergencyEvents(),
        api.getIntersections(),
      ]);
      setData(emRes);
      setIntersections(inters);
      if (inters.length > 0 && !intersectionId) {
        setIntersectionId(inters[0].id);
      }
    } catch (err) {
      console.error('Failed to load emergency data', err);
    } finally {
      setLoading(false);
    }
  }, [intersectionId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSubmitPreemption = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!intersectionId || !vehicleId.trim()) return;
    setSubmitting(true);
    try {
      // The response carries the Deterministic Safety Engine's verdict. A call
      // that failed validation is recorded as REJECTED, so the operator is
      // shown the verdict rather than a blanket success message.
      const result = await api.submitPreemption({
        intersection_id: intersectionId,
        vehicle_id: vehicleId,
        vehicle_type: vehicleType,
        requested_phase: targetPhase,
        source: 'FIRST_RESPONDER_CAD',
      });
      setLastVerdict(result);
      await loadData();
    } catch (err: any) {
      setLastVerdict({ status: 'ERROR', error: err.message });
    } finally {
      setSubmitting(false);
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
              EMERGENCY VEHICLE PREEMPTION (EVP)
            </h1>
            {/* Describes what the platform accepts, not a connection it has not
                measured: nothing here knows whether a CAD/AVL unit is reporting. */}
            <span
              className="status-badge"
              title="Vehicles report positions (NMEA RMC) to POST /api/v1/emergency/avl; operators can also request preemption below."
            >
              MANUAL + AVL (NMEA RMC)
            </span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            First responder corridor preemption with deterministic yellow change and red clearance intervals.
          </div>
        </div>

        <button onClick={loadData} className="its-btn" disabled={loading}>
          <RefreshCw size={13} className={loading ? 'pulse-indicator' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {(!data?.events || data.events.length === 0) && !loading ? (
        <TruthfulEmptyState
          title="EMERGENCY DATA UNAVAILABLE"
          description="No CAD/AVL dispatch or roadside optical preemption detectors are reporting active emergency preemption calls."
          icon={<Siren size={36} />}
        />
      ) : (
        <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="its-table-container" style={{ border: 'none' }}>
            <table className="its-table">
              <thead>
                <tr>
                  <th>Vehicle ID</th>
                  <th>Apparatus Type</th>
                  <th>Target Node</th>
                  <th>Requested Phase</th>
                  <th>Trigger</th>
                  <th>Safety Interlock</th>
                  <th>Preemption State</th>
                  <th>Controller</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {data.events.map((ev: any) => (
                  <tr key={ev.id}>
                    <td className="mono" style={{ fontWeight: 700, color: '#f87171' }}>{ev.vehicle_id}</td>
                    <td><span className="status-badge red">{ev.vehicle_type}</span></td>
                    <td className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-cyan)' }}>{ev.intersection_id?.slice(0, 8)}</td>
                    <td className="mono" style={{ color: '#38bdf8', fontWeight: 600 }}>
                      {ev.requested_phase != null ? `Phase ${ev.requested_phase}` : 'NO PHASE MAPPED'}
                    </td>
                    <td className="mono" style={{ fontSize: 'var(--text-2xs)' }}>
                      {ev.trigger || 'MANUAL'}
                      {ev.eta_sec != null && (
                        <div style={{ color: 'var(--its-text-muted)' }}>ETA {Math.round(ev.eta_sec)}s</div>
                      )}
                    </td>
                    <td>
                      <span className={`status-badge ${ev.safety_clearance_passed ? 'green' : 'red'}`}>
                        {ev.safety_clearance_passed ? 'SAFETY ENGINE PASSED' : 'INTERLOCK ACTIVE'}
                      </span>
                    </td>
                    <td><StatusBadge status={ev.status} /></td>
                    <td className="mono" style={{ fontSize: 'var(--text-2xs)' }}>
                      {ev.command_status || (ev.safety_clearance_passed ? 'NOT RECORDED' : 'NOT SENT')}
                    </td>
                    <td style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}>{ev.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Manual Preemption Dispatch Tool */}
      {intersections.length > 0 && (
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              <Siren size={15} color="#f87171" />
              <span>Submit First Responder Preemption Call</span>
            </span>
            <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              CAD / AVL INTEGRATION GATEWAY
            </span>
          </div>

          <form onSubmit={handleSubmitPreemption}>
            <div className="grid-4" style={{ marginBottom: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Apparatus Call Sign
                </label>
                <input
                  type="text"
                  className="its-input mono"
                  value={vehicleId}
                  placeholder="Vehicle ID from CAD, e.g. unit call sign"
                  onChange={(e) => setVehicleId(e.target.value)}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Vehicle Class
                </label>
                <select className="its-select" value={vehicleType} onChange={(e) => setVehicleType(e.target.value)}>
                  <option value="AMBULANCE">Ambulance (EMS)</option>
                  <option value="FIRE_ENGINE">Fire Engine (Structural)</option>
                  <option value="POLICE">Police Interceptor</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Target Intersection
                </label>
                <select className="its-select" value={intersectionId} onChange={(e) => setIntersectionId(e.target.value)}>
                  {intersections.map((inter) => (
                    <option key={inter.id} value={inter.id}>
                      {inter.name} ({inter.code})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Requested Preempt Phase
                </label>
                <select className="its-select" value={targetPhase} onChange={(e) => setTargetPhase(parseInt(e.target.value, 10))}>
                  <option value={2}>Phase 2 (Major Thru NB)</option>
                  <option value={4}>Phase 4 (Cross Street EB)</option>
                  <option value={6}>Phase 6 (Major Thru SB)</option>
                  <option value={8}>Phase 8 (Cross Street WB)</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button type="submit" className="its-btn its-btn-danger" disabled={submitting}>
                <Siren size={14} />
                <span>{submitting ? 'Verifying Clearance...' : 'Dispatch Emergency Preemption'}</span>
              </button>
            </div>

            {lastVerdict && <PreemptionVerdict verdict={lastVerdict} />}
          </form>
        </div>
      )}
    </div>
  );
};
