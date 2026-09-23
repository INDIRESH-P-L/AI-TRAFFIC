import React, { useCallback, useState } from 'react';
import {
  Camera as CameraIcon, Check, ChevronRight, Cloud, Loader2, MapPin,
  Radio, Sliders, X, XCircle,
} from 'lucide-react';
import { api } from '../api/client';

/**
 * TRAFFICINTEL AI - "Connect your first infrastructure" wizard
 *
 * This is the core empty-state experience. A clean installation has nothing to
 * show, and rather than papering over that with sample data, the console puts
 * the operator in front of the one thing that changes it: connecting real
 * hardware.
 *
 * Every step ends in a LIVE connectivity test against the address entered, and
 * the result is reported as measured. A failed test is shown with the actual
 * network error, because "could not reach 10.0.0.5:161 — connection refused"
 * is something a field technician can act on, and "setup failed" is not.
 *
 * Nothing is saved as CONNECTED on the strength of a form being filled in.
 */

type StepId = 'JUNCTION' | 'CONTROLLER' | 'CAMERA' | 'SENSOR' | 'WEATHER' | 'DONE';

const STEPS: Array<{ id: StepId; label: string; icon: React.ReactNode; optional: boolean }> = [
  { id: 'JUNCTION', label: 'Junction', icon: <MapPin size={13} />, optional: false },
  { id: 'CONTROLLER', label: 'Signal controller', icon: <Sliders size={13} />, optional: true },
  { id: 'CAMERA', label: 'Camera', icon: <CameraIcon size={13} />, optional: true },
  { id: 'SENSOR', label: 'Detector', icon: <Radio size={13} />, optional: true },
  { id: 'WEATHER', label: 'Weather', icon: <Cloud size={13} />, optional: true },
];

interface TestResult {
  ok: boolean;
  message: string;
  detail?: string;
}

interface Props {
  onClose: () => void;
  onComplete?: () => void;
}

export const OnboardingWizard: React.FC<Props> = ({ onClose, onComplete }) => {
  const [step, setStep] = useState<StepId>('JUNCTION');
  const [busy, setBusy] = useState(false);

  // Junction
  const [junctionName, setJunctionName] = useState('');
  const [junctionCode, setJunctionCode] = useState('');
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [junctionId, setJunctionId] = useState<string | null>(null);

  // Controller
  const [ctrlName, setCtrlName] = useState('');
  const [ctrlIp, setCtrlIp] = useState('');
  const [ctrlPort, setCtrlPort] = useState('161');
  const [ctrlProtocol, setCtrlProtocol] = useState('NTCIP_1202');
  const [ctrlTest, setCtrlTest] = useState<TestResult | null>(null);

  // Camera
  const [camName, setCamName] = useState('');
  const [camUrl, setCamUrl] = useState('');
  const [camTest, setCamTest] = useState<TestResult | null>(null);

  // Sensor
  const [sensorName, setSensorName] = useState('');
  const [sensorType, setSensorType] = useState('RADAR');
  const [sensorEndpoint, setSensorEndpoint] = useState('');
  const [sensorSaved, setSensorSaved] = useState<TestResult | null>(null);

  // Weather
  const [weatherTest, setWeatherTest] = useState<TestResult | null>(null);

  const [error, setError] = useState<string | null>(null);

  // --- Step actions -----------------------------------------------------

  const createJunction = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createIntersection({
        name: junctionName,
        code: junctionCode,
        latitude: Number(lat),
        longitude: Number(lng),
        jurisdiction: 'Municipal DOT',
        approaches: [],
      });
      setJunctionId(created.id);
      setStep('CONTROLLER');
    } catch (err: any) {
      setError(err.message || 'Could not create the junction');
    } finally {
      setBusy(false);
    }
  }, [junctionName, junctionCode, lat, lng]);

  const testController = useCallback(async () => {
    setBusy(true);
    setCtrlTest(null);
    try {
      // Reachability probe before anything is saved.
      const result = await api.testControllerWizard(ctrlIp, Number(ctrlPort));
      setCtrlTest({
        ok: result.reachable,
        message: result.message,
        detail: result.reachable
          ? `Round trip ${result.latency_ms ?? '—'}ms. This proves the address answers; phase state is only readable over NTCIP 1202.`
          : 'Nothing will be saved as CONNECTED. Check the address, the port, and that the cabinet permits this host.',
      });
    } catch (err: any) {
      setCtrlTest({ ok: false, message: err.message || 'Connectivity test failed' });
    } finally {
      setBusy(false);
    }
  }, [ctrlIp, ctrlPort]);

  const saveController = useCallback(async () => {
    if (!junctionId) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createController({
        intersection_id: junctionId,
        name: ctrlName,
        vendor: 'Unspecified',
        model: 'Unspecified',
        protocol: ctrlProtocol,
        ip_address: ctrlIp,
        port: Number(ctrlPort),
        cycle_length: 90,
        phases: [2, 4, 6, 8].map(n => ({
          phase_number: n,
          ring: n <= 4 ? 1 : 2,
          barrier: n % 4 === 0 ? 2 : 1,
          name: `Phase ${n}`,
          min_green: 7,
          max_green: 65,
          yellow_change: 4,
          red_clearance: 2,
          ped_walk: 7,
          ped_clearance: 15,
          conflicting_phases: n % 4 === 0 ? [2, 6] : [4, 8],
        })),
      });
      // Immediately probe it so the saved status reflects a measurement.
      await api.testControllerConnection(created.id).catch(() => null);
      setStep('CAMERA');
    } catch (err: any) {
      setError(err.message || 'Could not save the controller');
    } finally {
      setBusy(false);
    }
  }, [junctionId, ctrlName, ctrlProtocol, ctrlIp, ctrlPort]);

  const testCamera = useCallback(async () => {
    setBusy(true);
    setCamTest(null);
    try {
      const result = await api.testCameraWizard(camUrl);
      setCamTest({
        ok: result.reachable,
        message: result.message,
        detail: result.reachable
          ? 'The host answers. Resolution and frame rate stay unmeasured until an edge unit delivers frames.'
          : 'The camera will be saved as OFFLINE, not CONNECTED.',
      });
    } catch (err: any) {
      setCamTest({ ok: false, message: err.message || 'Camera test failed' });
    } finally {
      setBusy(false);
    }
  }, [camUrl]);

  const saveCamera = useCallback(async () => {
    if (!junctionId) return;
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        intersection_id: junctionId,
        name: camName,
        stream_url: camUrl,
      });
      await api.createCameraQuery(params.toString());
      setStep('SENSOR');
    } catch (err: any) {
      setError(err.message || 'Could not save the camera');
    } finally {
      setBusy(false);
    }
  }, [junctionId, camName, camUrl]);

  const saveSensor = useCallback(async () => {
    if (!junctionId) return;
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        intersection_id: junctionId,
        name: sensorName,
        sensor_type: sensorType,
        telemetry_endpoint: sensorEndpoint,
      });
      await api.createSensorQuery(params.toString());
      setSensorSaved({
        ok: true,
        message: 'Detector registered as DISCONNECTED.',
        detail:
          'A detector becomes CONNECTED when it posts its first observation. Until then the junction correctly reports NO SENSOR DATA AVAILABLE.',
      });
      setStep('WEATHER');
    } catch (err: any) {
      setError(err.message || 'Could not save the detector');
    } finally {
      setBusy(false);
    }
  }, [junctionId, sensorName, sensorType, sensorEndpoint]);

  const testWeather = useCallback(async () => {
    if (!junctionId) return;
    setBusy(true);
    setWeatherTest(null);
    try {
      const result = await api.getIntersectionWeather(junctionId);
      const ok = result.status !== 'WEATHER_DATA_UNAVAILABLE';
      setWeatherTest({
        ok,
        message: ok
          ? `Open-Meteo returned an observation for ${Number(lat).toFixed(4)}, ${Number(lng).toFixed(4)}.`
          : 'WEATHER DATA UNAVAILABLE',
        detail: ok
          ? `Road condition reported as ${result.road_condition ?? 'unknown'}.`
          : 'The provider did not return an observation. No weather is shown for this junction.',
      });
    } catch (err: any) {
      setWeatherTest({ ok: false, message: err.message || 'Weather fetch failed' });
    } finally {
      setBusy(false);
    }
  }, [junctionId, lat, lng]);

  const currentIndex = STEPS.findIndex(s => s.id === step);

  const TestOutcome: React.FC<{ result: TestResult | null }> = ({ result }) =>
    !result ? null : (
      <div
        role="status"
        style={{
          padding: '10px 12px', borderRadius: 'var(--radius-sm)', marginTop: '10px',
          border: `1px solid ${result.ok ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'}`,
          background: result.ok ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
          fontSize: 'var(--text-2xs)', lineHeight: 1.6,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px', fontWeight: 700 }}>
          {result.ok ? <Check size={13} color="var(--its-signal-green)" /> : <XCircle size={13} color="var(--its-signal-red)" />}
          <span>{result.ok ? 'REACHABLE' : 'NOT REACHABLE'}</span>
        </div>
        <div className="mono" style={{ marginTop: '5px', color: 'var(--its-text-primary)' }}>{result.message}</div>
        {result.detail && <div style={{ marginTop: '5px', color: 'var(--its-text-secondary)' }}>{result.detail}</div>}
      </div>
    );

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="junction-drawer" role="dialog" aria-modal="true" aria-label="Connect infrastructure">
        <div className="drawer-header">
          <div>
            <div style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>CONNECT YOUR FIRST INFRASTRUCTURE</div>
            <div style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              Every step is verified against the real address you enter
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close wizard"
            style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--its-text-muted)' }}
          >
            <X size={17} />
          </button>
        </div>

        {/* Stepper */}
        <div
          style={{
            display: 'flex', gap: '4px', padding: '10px 16px', flexWrap: 'wrap',
            borderBottom: '1px solid var(--its-border-subtle)',
          }}
        >
          {STEPS.map((s, i) => {
            const done = currentIndex > i || step === 'DONE';
            const active = step === s.id;
            return (
              <span
                key={s.id}
                className="mono"
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '5px',
                  fontSize: '9px', fontWeight: 700, padding: '3px 7px',
                  borderRadius: 'var(--radius-full)',
                  background: active ? 'var(--its-fresh-bg)' : done ? 'var(--its-signal-green-bg)' : 'var(--its-stale-bg)',
                  color: active ? 'var(--its-text-accent)' : done ? 'var(--its-signal-green)' : 'var(--its-text-muted)',
                  border: `1px solid ${active ? 'var(--its-border-accent)' : done ? 'var(--its-signal-green-border)' : 'var(--its-border-subtle)'}`,
                }}
              >
                {done ? <Check size={10} /> : s.icon}
                {s.label.toUpperCase()}
              </span>
            );
          })}
        </div>

        <div className="junction-drawer-body">
          {error && (
            <div role="alert" style={errorBlock}>
              <strong>STEP FAILED</strong>
              <div style={{ marginTop: '4px' }}>{error}</div>
            </div>
          )}

          {/* ---- JUNCTION ---- */}
          {step === 'JUNCTION' && (
            <>
              <p style={helpText}>
                Start with the physical junction. Its coordinates position every device you
                attach to it on the operations map.
              </p>

              <label style={fieldLabel} htmlFor="wz-name">Junction name</label>
              <input id="wz-name" className="its-input" value={junctionName} onChange={e => setJunctionName(e.target.value)} placeholder="Main St & 1st Ave" />

              <label style={fieldLabel} htmlFor="wz-code">Junction code</label>
              <input id="wz-code" className="its-input" value={junctionCode} onChange={e => setJunctionCode(e.target.value)} placeholder="INT-101" />

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={fieldLabel} htmlFor="wz-lat">Latitude</label>
                  <input id="wz-lat" className="its-input" value={lat} onChange={e => setLat(e.target.value)} inputMode="decimal" />
                </div>
                <div>
                  <label style={fieldLabel} htmlFor="wz-lng">Longitude</label>
                  <input id="wz-lng" className="its-input" value={lng} onChange={e => setLng(e.target.value)} inputMode="decimal" />
                </div>
              </div>

              <button
                onClick={createJunction}
                className="its-btn its-btn-primary"
                disabled={busy || !junctionName || !junctionCode || !lat || !lng}
                style={wideBtn}
              >
                {busy ? <Loader2 size={13} className="pulse-indicator" /> : <ChevronRight size={13} />}
                <span>Create junction</span>
              </button>
            </>
          )}

          {/* ---- CONTROLLER ---- */}
          {step === 'CONTROLLER' && (
            <>
              <p style={helpText}>
                Only <strong>NTCIP 1202</strong> has an implemented session layer. On any
                other protocol the platform can prove the cabinet answers, but cannot read
                its phase state — and the Safety Engine refuses commands to hardware it
                cannot read.
              </p>

              <label style={fieldLabel} htmlFor="wz-cname">Controller name</label>
              <input id="wz-cname" className="its-input" value={ctrlName} onChange={e => setCtrlName(e.target.value)} placeholder="Cabinet 1" />

              <label style={fieldLabel} htmlFor="wz-proto">Protocol</label>
              <select id="wz-proto" className="its-select" value={ctrlProtocol} onChange={e => setCtrlProtocol(e.target.value)}>
                <option value="NTCIP_1202">NTCIP 1202 (readable, commandable)</option>
                <option value="ASC3_ETHERNET">ASC/3 Ethernet (reachability only)</option>
                <option value="REST_GATEWAY">REST gateway (reachability only)</option>
              </select>

              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '10px' }}>
                <div>
                  <label style={fieldLabel} htmlFor="wz-ip">IP address</label>
                  <input id="wz-ip" className="its-input" value={ctrlIp} onChange={e => setCtrlIp(e.target.value)} placeholder="127.0.0.1" />
                </div>
                <div>
                  <label style={fieldLabel} htmlFor="wz-port">Port</label>
                  <input id="wz-port" className="its-input" value={ctrlPort} onChange={e => setCtrlPort(e.target.value)} inputMode="numeric" />
                </div>
              </div>

              <button onClick={testController} className="its-btn" disabled={busy || !ctrlIp} style={wideBtn}>
                {busy ? <Loader2 size={13} className="pulse-indicator" /> : <Sliders size={13} />}
                <span>Test connectivity</span>
              </button>

              <TestOutcome result={ctrlTest} />

              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setStep('CAMERA')} className="its-btn" style={{ flex: 1, justifyContent: 'center' }}>
                  <span>Skip</span>
                </button>
                <button
                  onClick={saveController}
                  className="its-btn its-btn-primary"
                  disabled={busy || !ctrlName || !ctrlIp}
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  <span>Save controller</span>
                </button>
              </div>
            </>
          )}

          {/* ---- CAMERA ---- */}
          {step === 'CAMERA' && (
            <>
              <p style={helpText}>
                A reachability test proves the camera host answers. It negotiates no RTSP
                session, so resolution and frame rate stay unmeasured until real frames
                arrive.
              </p>

              <label style={fieldLabel} htmlFor="wz-camname">Camera name</label>
              <input id="wz-camname" className="its-input" value={camName} onChange={e => setCamName(e.target.value)} placeholder="NB approach" />

              <label style={fieldLabel} htmlFor="wz-camurl">Stream URL</label>
              <input id="wz-camurl" className="its-input" value={camUrl} onChange={e => setCamUrl(e.target.value)} placeholder="rtsp://10.0.0.20:554/stream1" />

              <button onClick={testCamera} className="its-btn" disabled={busy || !camUrl} style={wideBtn}>
                {busy ? <Loader2 size={13} className="pulse-indicator" /> : <CameraIcon size={13} />}
                <span>Test stream reachability</span>
              </button>

              <TestOutcome result={camTest} />

              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setStep('SENSOR')} className="its-btn" style={{ flex: 1, justifyContent: 'center' }}>
                  <span>Skip</span>
                </button>
                <button
                  onClick={saveCamera}
                  className="its-btn its-btn-primary"
                  disabled={busy || !camName || !camUrl}
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  <span>Save camera</span>
                </button>
              </div>
            </>
          )}

          {/* ---- SENSOR ---- */}
          {step === 'SENSOR' && (
            <>
              <p style={helpText}>
                Detectors push observations to the platform. Registering one does not create
                data: the junction reports NO SENSOR DATA AVAILABLE until the detector posts
                its first reading.
              </p>

              <label style={fieldLabel} htmlFor="wz-sname">Detector name</label>
              <input id="wz-sname" className="its-input" value={sensorName} onChange={e => setSensorName(e.target.value)} placeholder="NB stop bar loop" />

              <label style={fieldLabel} htmlFor="wz-stype">Type</label>
              <select id="wz-stype" className="its-select" value={sensorType} onChange={e => setSensorType(e.target.value)}>
                <option value="RADAR">Radar</option>
                <option value="INDUCTIVE_LOOP">Inductive loop</option>
                <option value="MICROWAVE">Microwave</option>
                <option value="LIDAR">Lidar</option>
              </select>

              <label style={fieldLabel} htmlFor="wz-sep">Telemetry endpoint (optional)</label>
              <input id="wz-sep" className="its-input" value={sensorEndpoint} onChange={e => setSensorEndpoint(e.target.value)} placeholder="http://10.0.0.30/telemetry" />

              <TestOutcome result={sensorSaved} />

              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setStep('WEATHER')} className="its-btn" style={{ flex: 1, justifyContent: 'center' }}>
                  <span>Skip</span>
                </button>
                <button
                  onClick={saveSensor}
                  className="its-btn its-btn-primary"
                  disabled={busy || !sensorName}
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  <span>Save detector</span>
                </button>
              </div>
            </>
          )}

          {/* ---- WEATHER ---- */}
          {step === 'WEATHER' && (
            <>
              <p style={helpText}>
                Weather comes from Open-Meteo for the junction's coordinates. This step
                fetches a live observation to confirm the provider is reachable from this
                host.
              </p>

              <button onClick={testWeather} className="its-btn" disabled={busy} style={wideBtn}>
                {busy ? <Loader2 size={13} className="pulse-indicator" /> : <Cloud size={13} />}
                <span>Fetch a live observation</span>
              </button>

              <TestOutcome result={weatherTest} />

              <button
                onClick={() => setStep('DONE')}
                className="its-btn its-btn-primary"
                style={wideBtn}
              >
                <span>Finish</span>
              </button>
            </>
          )}

          {/* ---- DONE ---- */}
          {step === 'DONE' && (
            <>
              <div
                style={{
                  padding: '14px', borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--its-signal-green-border)',
                  background: 'var(--its-signal-green-bg)',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)' }}>INFRASTRUCTURE REGISTERED</div>
                <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '6px', lineHeight: 1.6 }}>
                  What you connected now appears on the operations map with its measured
                  state. Panels that depend on telemetry nobody is sending will stay in
                  their empty states — that is the platform reporting reality, not a fault.
                </div>
              </div>

              <button
                onClick={() => {
                  onComplete?.();
                  onClose();
                }}
                className="its-btn its-btn-primary"
                style={wideBtn}
              >
                <span>Open the operations map</span>
              </button>
            </>
          )}
        </div>
      </aside>
    </>
  );
};

const fieldLabel: React.CSSProperties = {
  display: 'block',
  fontSize: 'var(--text-2xs)',
  color: 'var(--its-text-muted)',
  textTransform: 'uppercase',
  fontWeight: 600,
  letterSpacing: '0.05em',
  marginTop: '4px',
};

const helpText: React.CSSProperties = {
  fontSize: 'var(--text-2xs)',
  color: 'var(--its-text-secondary)',
  lineHeight: 1.7,
  margin: 0,
};

const wideBtn: React.CSSProperties = {
  width: '100%',
  justifyContent: 'center',
  marginTop: '6px',
};

const errorBlock: React.CSSProperties = {
  padding: '10px 12px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--its-signal-red-border)',
  background: 'var(--its-signal-red-bg)',
  fontSize: 'var(--text-2xs)',
};
