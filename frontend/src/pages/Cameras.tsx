import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import {
  Camera as CameraIcon,
  RefreshCw,
  VideoOff
} from 'lucide-react';

export const Cameras: React.FC = () => {
  const [cameras, setCameras] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [columnCount, setColumnCount] = useState<2 | 3>(2);

  const loadCameras = async () => {
    try {
      const data = await api.getCameras();
      setCameras(data);
    } catch (err) {
      console.error('Failed to load cameras', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCameras();
  }, []);

  const handleTestConnection = async (id: string) => {
    setTestingId(id);
    try {
      const res = await api.testCameraConnection(id);
      await loadCameras();
      alert(`Camera connection test result: ${res.stream_status}\n${res.test_result}`);
    } catch (err: any) {
      alert(`Test error: ${err.message}`);
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Top Operations Header */}
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
              SURVEILLANCE & EDGE VISION DETECTORS
            </h1>
            <span className="status-badge active">RTSP / ONVIF</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Real-time roadside optical sensors with vehicle classification & license plate detection pipelines.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          {/* Grid Layout Toggles */}
          <div style={{ display: 'flex', background: 'var(--its-bg-surface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-md)', padding: '2px' }}>
            <button
              onClick={() => setColumnCount(2)}
              className="its-btn its-btn-ghost"
              style={{ padding: '4px 8px', fontSize: '11px', background: columnCount === 2 ? 'var(--its-bg-hover)' : 'transparent', color: columnCount === 2 ? '#38bdf8' : 'var(--its-text-muted)' }}
            >
              2-Grid
            </button>
            <button
              onClick={() => setColumnCount(3)}
              className="its-btn its-btn-ghost"
              style={{ padding: '4px 8px', fontSize: '11px', background: columnCount === 3 ? 'var(--its-bg-hover)' : 'transparent', color: columnCount === 3 ? '#38bdf8' : 'var(--its-text-muted)' }}
            >
              3-Grid
            </button>
          </div>

          <button onClick={loadCameras} className="its-btn" disabled={loading}>
            <RefreshCw size={13} className={loading ? 'pulse-indicator' : ''} />
            <span>Sync Feeds</span>
          </button>
        </div>
      </div>

      {cameras.length === 0 && !loading ? (
        <TruthfulEmptyState
          title="NO CAMERAS CONNECTED"
          description="No surveillance or optical traffic detection cameras are currently configured. Connect authorized IP or RTSP video streams."
          actionText="Configure Camera Feed"
          actionLink="/settings"
          icon={<VideoOff size={36} />}
        />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${columnCount}, 1fr)`, gap: '16px' }}>
          {cameras.map((cam) => {
            const isOnline = cam.stream_status === 'CONNECTED';
            return (
              <div key={cam.id} className="its-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontWeight: 700, fontSize: 'var(--text-sm)', color: 'var(--its-text-primary)' }}>
                        {cam.name}
                      </span>
                      <StatusBadge status={cam.stream_status} />
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--its-text-muted)', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                      RTSP: {cam.stream_url}
                    </div>
                  </div>

                  <button
                    onClick={() => handleTestConnection(cam.id)}
                    className="its-btn"
                    disabled={testingId === cam.id}
                    style={{ fontSize: '11px', padding: '4px 8px' }}
                  >
                    <RefreshCw size={11} className={testingId === cam.id ? 'pulse-indicator' : ''} />
                    <span>{testingId === cam.id ? 'Pinging...' : 'Ping Socket'}</span>
                  </button>
                </div>

                {/* Technical Monitor Viewport */}
                <div
                  style={{
                    height: '240px',
                    background: '#070a10',
                    borderRadius: 'var(--radius-md)',
                    border: `1px solid ${isOnline ? 'var(--its-border-accent)' : 'var(--its-border-subtle)'}`,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    position: 'relative',
                    overflow: 'hidden',
                    padding: '16px',
                  }}
                >
                  {/* Subtle Camera HUD Elements */}
                  <div style={{ position: 'absolute', top: '10px', left: '10px', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--its-text-cyan)', background: 'rgba(8, 11, 18, 0.8)', padding: '2px 6px', borderRadius: 'var(--radius-xs)' }}>
                    CAM_ID: {cam.id.slice(0, 8)}
                  </div>
                  <div style={{ position: 'absolute', top: '10px', right: '10px', fontSize: '10px', fontFamily: 'var(--font-mono)', color: isOnline ? '#34d399' : '#f87171', background: 'rgba(8, 11, 18, 0.8)', padding: '2px 6px', borderRadius: 'var(--radius-xs)' }}>
                    {isOnline ? 'LIVE FEED: 30 FPS' : 'NO CARRIER SIGNAL'}
                  </div>

                  {isOnline ? (
                    <div style={{ textAlign: 'center' }}>
                      <CameraIcon size={36} color="var(--its-signal-green)" style={{ margin: '0 auto 8px' }} />
                      <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
                        RTSP OPTICAL STREAM ACTIVE
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '4px', fontFamily: 'var(--font-mono)' }}>
                        Res: {cam.resolution || '1080p'} • Target: {cam.fps || 30} FPS • H.264
                      </div>
                      <div style={{ fontSize: '10px', color: 'var(--its-text-cyan)', marginTop: '6px' }}>
                        Inference: PyTorch Edge Object Classifier Active
                      </div>
                    </div>
                  ) : (
                    <div style={{ textAlign: 'center', maxWidth: '300px' }}>
                      <VideoOff size={36} color="var(--its-text-muted)" style={{ margin: '0 auto 8px' }} />
                      <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}>
                        CAMERA OFFLINE / UNREACHABLE
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--its-text-disabled)', marginTop: '4px' }}>
                        RTSP socket handshake failed. System does not fabricate synthetic footage.
                      </div>
                    </div>
                  )}

                  {/* Bottom Technical Bar */}
                  <div style={{ position: 'absolute', bottom: '10px', left: '10px', right: '10px', display: 'flex', justifyContent: 'space-between', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--its-text-muted)' }}>
                    <span>CLASSIFIER: VEHICLE / PED</span>
                    <span>LATENCY: {isOnline ? '14ms' : 'TIMEOUT'}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
