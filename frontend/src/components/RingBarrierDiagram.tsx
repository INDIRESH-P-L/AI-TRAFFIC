import React from 'react';

interface PhaseInfo {
  phase_number: number;
  name: string;
  ring: number;
  barrier: number;
  min_green: number;
  max_green: number;
}

interface RingBarrierProps {
  phases: PhaseInfo[];
  activePhase?: number | null;
  activeSeconds?: number;
}

export const RingBarrierDiagram: React.FC<RingBarrierProps> = ({
  phases = [],
  activePhase,
  activeSeconds = 0,
}) => {
  // If controller is unconfigured
  if (!phases || phases.length === 0) {
    return (
      <div
        style={{
          padding: '24px',
          textAlign: 'center',
          color: 'var(--its-text-muted)',
          fontSize: 'var(--text-sm)',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--its-bg-surface)',
        }}
      >
        SIGNAL PHASES NOT CONFIGURED
      </div>
    );
  }

  const ring1 = phases.filter((p) => p.ring === 1).sort((a, b) => a.phase_number - b.phase_number);
  const ring2 = phases.filter((p) => p.ring === 2).sort((a, b) => a.phase_number - b.phase_number);

  const renderPhaseBox = (p: PhaseInfo) => {
    const isActive = activePhase === p.phase_number;
    return (
      <div
        key={p.phase_number}
        style={{
          flex: 1,
          padding: '10px',
          background: isActive ? 'var(--its-signal-green-bg)' : 'var(--its-bg-card)',
          border: `1px solid ${isActive ? 'var(--its-signal-green)' : 'var(--its-border-subtle)'}`,
          borderRadius: 'var(--radius-sm)',
          minWidth: '100px',
          textAlign: 'center',
          position: 'relative',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
          <span
            style={{
              fontWeight: 700,
              fontSize: 'var(--text-xs)',
              color: isActive ? 'var(--its-signal-green)' : 'var(--its-text-primary)',
            }}
          >
            Φ{p.phase_number}
          </span>
          {isActive && (
            <span
              style={{
                fontSize: '0.7rem',
                fontWeight: 700,
                color: '#047857',
                background: '#d1fae5',
                border: '1px solid #a7f3d0',
                padding: '1px 6px',
                borderRadius: 'var(--radius-xs)',
              }}
            >
              ACTIVE {activeSeconds}s
            </span>
          )}
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--its-text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {p.name}
        </div>
        <div style={{ fontSize: '0.65rem', color: 'var(--its-text-muted)', marginTop: '4px' }}>
          Min: {p.min_green}s | Max: {p.max_green}s
        </div>
      </div>
    );
  };

  return (
    <div
      style={{
        background: 'var(--its-bg-surface)',
        border: '1px solid var(--its-border-subtle)',
        borderRadius: 'var(--radius-md)',
        padding: '16px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
        <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--its-text-muted)', textTransform: 'uppercase' }}>
          NEMA TS 2 Dual-Ring Barrier State
        </span>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)' }}>
          Active Indication: {activePhase ? `Phase ${activePhase} (GREEN)` : 'UNAVAILABLE / ALL RED'}
        </span>
      </div>

      {/* Ring 1 */}
      <div style={{ marginBottom: '8px' }}>
        <div style={{ fontSize: '0.7rem', color: 'var(--its-text-muted)', marginBottom: '4px' }}>RING 1</div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {ring1.map(renderPhaseBox)}
        </div>
      </div>

      {/* Barrier line */}
      <div
        style={{
          height: '2px',
          background: 'var(--its-border-default)',
          margin: '10px 0',
          position: 'relative',
        }}
      >
        <span
          style={{
            position: 'absolute',
            right: 0,
            top: '-8px',
            fontSize: '0.65rem',
            background: 'var(--its-bg-surface)',
            padding: '0 4px',
            color: 'var(--its-text-muted)',
          }}
        >
          BARRIER
        </span>
      </div>

      {/* Ring 2 */}
      <div>
        <div style={{ fontSize: '0.7rem', color: 'var(--its-text-muted)', marginBottom: '4px' }}>RING 2</div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {ring2.map(renderPhaseBox)}
        </div>
      </div>
    </div>
  );
};
