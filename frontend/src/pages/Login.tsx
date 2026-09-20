import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Lock, User as UserIcon, AlertCircle, ShieldCheck } from 'lucide-react';

export const Login: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('TrafficIntel2026!');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await login(username, password);
      navigate('/dashboard');
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Please verify credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100vw',
        display: 'flex',
        backgroundColor: '#ffffff',
        overflow: 'hidden',
      }}
    >
      {/* --------------------------------------------------------------------
          LEFT SIDE: Abstract Stylized Traffic-Network Branding Visualization
          -------------------------------------------------------------------- */}
      <div
        style={{
          flex: 1.15,
          background: 'linear-gradient(145deg, #f8fafc 0%, #f0fdfa 45%, #eff6ff 100%)',
          borderRight: '1px solid #e2e8f0',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '48px 56px',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Subtle decorative background gridlines */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: `
              linear-gradient(to right, rgba(37, 99, 235, 0.04) 1px, transparent 1px),
              linear-gradient(to bottom, rgba(37, 99, 235, 0.04) 1px, transparent 1px)
            `,
            backgroundSize: '40px 40px',
            pointerEvents: 'none',
          }}
        />

        {/* Brand Top Header */}
        <div style={{ position: 'relative', zIndex: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '8px',
                background: 'linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#ffffff',
                boxShadow: '0 4px 12px rgba(37, 99, 235, 0.25)',
              }}
            >
              {/* Abstract Traffic Geometric Icon */}
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" fill="#ffffff" />
                <path d="M12 2v7M12 15v7M2 12h7M15 12h7" />
                <path d="M4.93 4.93l4.24 4.24M14.83 14.83l4.24 4.24" strokeDasharray="2 2" />
              </svg>
            </div>
            <div>
              <div style={{ fontSize: '18px', fontWeight: 800, letterSpacing: '0.05em', color: '#0f172a' }}>
                TRAFFICINTEL AI
              </div>
              <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.12em', color: '#0d9488', textTransform: 'uppercase' }}>
                REAL-TIME TRAFFIC INTELLIGENCE
              </div>
            </div>
          </div>
        </div>

        {/* Center: Abstract Animated Intersection Network (Branding Only) */}
        <div
          style={{
            position: 'relative',
            zIndex: 10,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '20px 0',
          }}
        >
          <svg width="420" height="340" viewBox="0 0 420 340" style={{ overflow: 'visible' }}>
            <defs>
              <linearGradient id="roadGradH" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#cbd5e1" stopOpacity="0.2" />
                <stop offset="50%" stopColor="#94a3b8" stopOpacity="0.8" />
                <stop offset="100%" stopColor="#cbd5e1" stopOpacity="0.2" />
              </linearGradient>

              <linearGradient id="roadGradV" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#cbd5e1" stopOpacity="0.2" />
                <stop offset="50%" stopColor="#94a3b8" stopOpacity="0.8" />
                <stop offset="100%" stopColor="#cbd5e1" stopOpacity="0.2" />
              </linearGradient>

              <linearGradient id="flowBlue" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#2563eb" />
                <stop offset="100%" stopColor="#0d9488" />
              </linearGradient>

              <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
            </defs>

            {/* Arterial Corridor 1 (Horizontal) */}
            <line x1="20" y1="170" x2="400" y2="170" stroke="url(#roadGradH)" strokeWidth="18" strokeLinecap="round" />
            <line x1="20" y1="170" x2="400" y2="170" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="6 6" />

            {/* Cross Arterial 1 (Vertical Left) */}
            <line x1="140" y1="30" x2="140" y2="310" stroke="url(#roadGradV)" strokeWidth="14" strokeLinecap="round" />
            <line x1="140" y1="30" x2="140" y2="310" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="6 6" />

            {/* Cross Arterial 2 (Vertical Right) */}
            <line x1="280" y1="30" x2="280" y2="310" stroke="url(#roadGradV)" strokeWidth="14" strokeLinecap="round" />
            <line x1="280" y1="30" x2="280" y2="310" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="6 6" />

            {/* Diagonal Bypass Flow Arc */}
            <path
              d="M 140 170 Q 210 240 280 170"
              fill="none"
              stroke="#0d9488"
              strokeWidth="2.5"
              strokeDasharray="4 4"
              opacity="0.75"
            />

            {/* Animated Flow Trajectories */}
            <path
              d="M 20 170 L 400 170"
              fill="none"
              stroke="url(#flowBlue)"
              strokeWidth="3.5"
              strokeDasharray="24 60"
              strokeLinecap="round"
              filter="url(#softGlow)"
            >
              <animate attributeName="stroke-dashoffset" from="168" to="0" dur="4s" repeatCount="indefinite" />
            </path>

            <path
              d="M 140 30 L 140 310"
              fill="none"
              stroke="#2563eb"
              strokeWidth="2.5"
              strokeDasharray="16 48"
              strokeLinecap="round"
            >
              <animate attributeName="stroke-dashoffset" from="128" to="0" dur="3.5s" repeatCount="indefinite" />
            </path>

            <path
              d="M 280 310 L 280 30"
              fill="none"
              stroke="#0d9488"
              strokeWidth="2.5"
              strokeDasharray="16 48"
              strokeLinecap="round"
            >
              <animate attributeName="stroke-dashoffset" from="0" to="128" dur="3.8s" repeatCount="indefinite" />
            </path>

            {/* Signalized Junction Node A (140, 170) */}
            <g transform="translate(140, 170)">
              <circle r="18" fill="rgba(37, 99, 235, 0.12)" />
              <circle r="9" fill="#ffffff" stroke="#2563eb" strokeWidth="2.5" />
              <circle r="4" fill="#10b981">
                <animate attributeName="opacity" values="1;0.4;1" dur="2.5s" repeatCount="indefinite" />
              </circle>
            </g>

            {/* Signalized Junction Node B (280, 170) */}
            <g transform="translate(280, 170)">
              <circle r="18" fill="rgba(13, 148, 136, 0.12)" />
              <circle r="9" fill="#ffffff" stroke="#0d9488" strokeWidth="2.5" />
              <circle r="4" fill="#2563eb">
                <animate attributeName="opacity" values="0.4;1;0.4" dur="2.5s" repeatCount="indefinite" />
              </circle>
            </g>
          </svg>
        </div>

        {/* Refined Brand Statement */}
        <div style={{ position: 'relative', zIndex: 10 }}>
          <p style={{ fontSize: '15px', fontWeight: 600, color: '#334155', lineHeight: 1.5, maxWidth: '420px' }}>
            Intelligence at the intersection of mobility, safety and control.
          </p>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: '6px', fontFamily: 'var(--font-mono)' }}>
            NEMA TS 2 • NTCIP 1202 • FHWA MUTCD GROUNDED
          </div>
        </div>
      </div>

      {/* --------------------------------------------------------------------
          RIGHT SIDE: Minimal, Clean Light Authentication Panel
          -------------------------------------------------------------------- */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px',
          background: '#ffffff',
        }}
      >
        <div style={{ width: '100%', maxWidth: '420px' }}>
          {/* Header */}
          <div style={{ marginBottom: '32px' }}>
            <div
              style={{
                fontSize: '11px',
                fontWeight: 700,
                letterSpacing: '0.1em',
                color: '#2563eb',
                textTransform: 'uppercase',
                fontFamily: 'var(--font-mono)',
                marginBottom: '6px',
              }}
            >
              WELCOME BACK
            </div>
            <h1
              style={{
                fontSize: '24px',
                fontWeight: 800,
                color: '#0f172a',
                letterSpacing: '-0.02em',
                lineHeight: 1.2,
              }}
            >
              Traffic Operations Control Center
            </h1>
            <p style={{ fontSize: '13px', color: '#64748b', marginTop: '6px' }}>
              Authorized operator access and telemetry console
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '10px 14px',
                background: '#fef2f2',
                border: '1px solid #fecaca',
                borderRadius: '8px',
                color: '#b91c1c',
                fontSize: '12px',
                marginBottom: '20px',
              }}
            >
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '12px',
                  fontWeight: 700,
                  color: '#334155',
                  marginBottom: '6px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                Operator ID
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  className="its-input"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Enter operator call sign"
                  required
                  style={{
                    paddingLeft: '36px',
                    height: '42px',
                    fontSize: '13px',
                    borderRadius: '8px',
                    borderColor: '#cbd5e1',
                  }}
                />
                <UserIcon
                  size={16}
                  style={{ position: 'absolute', left: '12px', top: '13px', color: '#94a3b8' }}
                />
              </div>
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '12px',
                  fontWeight: 700,
                  color: '#334155',
                  marginBottom: '6px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                Access Credential
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type="password"
                  className="its-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter security token / password"
                  required
                  style={{
                    paddingLeft: '36px',
                    height: '42px',
                    fontSize: '13px',
                    borderRadius: '8px',
                    borderColor: '#cbd5e1',
                  }}
                />
                <Lock
                  size={16}
                  style={{ position: 'absolute', left: '12px', top: '13px', color: '#94a3b8' }}
                />
              </div>
            </div>

            <button
              type="submit"
              className="its-btn its-btn-primary"
              style={{
                width: '100%',
                height: '44px',
                fontSize: '13px',
                fontWeight: 700,
                letterSpacing: '0.03em',
                justifyContent: 'center',
                borderRadius: '8px',
                marginTop: '6px',
                cursor: 'pointer',
              }}
              disabled={loading}
            >
              <span>{loading ? 'Authenticating...' : 'ENTER COMMAND CENTER →'}</span>
            </button>
          </form>

          {/* Secondary reassurance line */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              marginTop: '24px',
              color: '#64748b',
              fontSize: '11px',
            }}
          >
            <ShieldCheck size={14} color="#10b981" />
            <span>Secure operational access • 256-bit encrypted session</span>
          </div>
        </div>
      </div>
    </div>
  );
};
