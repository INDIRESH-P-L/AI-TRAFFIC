import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { Radio, Send, RefreshCw } from 'lucide-react';

export const Sensors: React.FC = () => {
  const [sensors, setSensors] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Diagnostic Telemetry Ingestion Hub
  const [selectedSensorId, setSelectedSensorId] = useState<string>('');
  const [vehicleCount, setVehicleCount] = useState<number>(18);
  const [occupancyPct, setOccupancyPct] = useState<number>(22.4);
  const [speedKph, setSpeedKph] = useState<number>(52.0);
  const [sending, setSending] = useState(false);

  const loadSensors = async () => {
    try {
      const data = await api.getSensors();
      setSensors(data);
      if (data.length > 0 && !selectedSensorId) {
        setSelectedSensorId(data[0].id);
      }
    } catch (err) {
      console.error('Failed to load sensors', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSensors();
  }, []);

  const handleSendTelemetry = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSensorId) return;
    setSending(true);

    try {
      const payload = {
        vehicle_count: vehicleCount,
        occupancy_pct: occupancyPct,
        avg_speed_kph: speedKph,
        timestamp: new Date().toISOString(),
      };

      const res = await fetch(`/api/v1/sensors/${selectedSensorId}/telemetry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error('Telemetry ingestion rejected');
      await loadSensors();
      alert('Detector telemetry packet ingested with validated quality provenance.');
    } catch (err: any) {
      alert(`Ingestion error: ${err.message}`);
    } finally {
      setSending(false);
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
              ROADSIDE SENSOR & DETECTOR TELEMETRY
            </h1>
            <span className="status-badge active">RADAR / LOOPS</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Inductive loops, microwave radar, and acoustic roadside detector packet streams with provenance validation.
          </div>
        </div>

        <button onClick={loadSensors} className="its-btn" disabled={loading}>
          <RefreshCw size={13} className={loading ? 'pulse-indicator' : ''} />
          <span>Sync Sensors</span>
        </button>
      </div>

      {sensors.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="NO SENSOR DATA AVAILABLE"
          description="No roadside sensor adapters have been registered. Add radar detectors, microwave sensors, or inductive loop cards."
          actionText="Configure Sensor"
          actionLink="/settings"
          icon={<Radio size={36} />}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Sensors Registry Table */}
          <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="its-table-container" style={{ border: 'none' }}>
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Detector Identifier</th>
                    <th>Sensor Modality</th>
                    <th>Node Association</th>
                    <th>Channel / Interface</th>
                    <th>Signal Quality</th>
                    <th>Hardware Status</th>
                  </tr>
                </thead>
                <tbody>
                  {sensors.map((s) => (
                    <tr key={s.id}>
                      <td style={{ fontWeight: 700, color: 'var(--its-text-primary)' }}>{s.name}</td>
                      <td>
                        <span className="status-badge neutral">{s.sensor_type}</span>
                      </td>
                      <td className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-cyan)' }}>
                        {s.intersection_id?.slice(0, 8) || 'GLOBAL'}
                      </td>
                      <td className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)' }}>
                        {s.telemetry_endpoint || 'Direct Serial / Loop Rack'}
                      </td>
                      <td><StatusBadge status={s.quality} /></td>
                      <td><StatusBadge status={s.health_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Telemetry Ingestion Hub */}
          <div className="its-card">
            <div className="its-card-header">
              <span className="its-card-title">
                <Send size={15} color="var(--its-text-cyan)" />
                <span>Roadside Detector Ingestion Hub (API Tool)</span>
              </span>
              <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                POST /api/v1/sensors/:id/telemetry
              </span>
            </div>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '16px' }}>
              Direct edge packet forwarder: ingest volume, occupancy, and speed into the Data Quality Engine.
            </p>

            <form onSubmit={handleSendTelemetry}>
              <div className="grid-4" style={{ marginBottom: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Target Sensor
                  </label>
                  <select
                    className="its-select"
                    value={selectedSensorId}
                    onChange={(e) => setSelectedSensorId(e.target.value)}
                  >
                    {sensors.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} ({s.sensor_type})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Vehicles Observed
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="500"
                    className="its-input"
                    value={vehicleCount}
                    onChange={(e) => setVehicleCount(parseInt(e.target.value, 10))}
                    required
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Occupancy (%)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="100"
                    className="its-input"
                    value={occupancyPct}
                    onChange={(e) => setOccupancyPct(parseFloat(e.target.value))}
                    required
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                    Average Speed (km/h)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="200"
                    className="its-input"
                    value={speedKph}
                    onChange={(e) => setSpeedKph(parseFloat(e.target.value))}
                    required
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button type="submit" className="its-btn its-btn-primary" disabled={sending || !selectedSensorId}>
                  <Send size={13} />
                  <span>{sending ? 'Validating Packet...' : 'Ingest Observation Packet'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
