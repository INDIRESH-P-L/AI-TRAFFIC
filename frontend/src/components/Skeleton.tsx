import React from 'react';

/**
 * Loading placeholders.
 *
 * A skeleton must be unmistakably "not yet loaded". It carries no digits and
 * no units, because a shimmering block that looks like a number is exactly the
 * kind of thing an operator glances at and reads as data. Each skeleton is
 * announced with aria-busy and a text alternative for screen readers.
 */

export const Skeleton: React.FC<{
  width?: string | number;
  height?: string | number;
  radius?: string;
  style?: React.CSSProperties;
}> = ({ width = '100%', height = 14, radius = 'var(--radius-xs)', style }) => (
  <div
    className="skeleton"
    aria-hidden="true"
    style={{ width, height, borderRadius: radius, ...style }}
  />
);

export const SkeletonText: React.FC<{ lines?: number; width?: string }> = ({
  lines = 3,
  width = '100%',
}) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: '7px', width }}>
    {Array.from({ length: lines }).map((_, i) => (
      <Skeleton key={i} width={i === lines - 1 ? '65%' : '100%'} />
    ))}
  </div>
);

/** A stat tile placeholder: label bar, value bar, provenance chip bar. */
export const SkeletonMetric: React.FC = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
    <Skeleton width="45%" height={9} />
    <Skeleton width="70%" height={20} />
    <Skeleton width="55%" height={12} radius="var(--radius-full)" />
  </div>
);

export const SkeletonCard: React.FC<{
  label: string;
  metrics?: number;
  lines?: number;
}> = ({ label, metrics = 0, lines = 3 }) => (
  <div className="its-card" aria-busy="true" aria-live="polite">
    <span className="visually-hidden">{label} is loading</span>
    <div className="its-card-header">
      <Skeleton width="40%" height={11} />
      <Skeleton width={70} height={11} />
    </div>
    {metrics > 0 ? (
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${Math.min(metrics, 4)}, minmax(0, 1fr))`,
          gap: '14px',
        }}
      >
        {Array.from({ length: metrics }).map((_, i) => (
          <SkeletonMetric key={i} />
        ))}
      </div>
    ) : (
      <SkeletonText lines={lines} />
    )}
  </div>
);

export const SkeletonRows: React.FC<{ rows?: number; label: string }> = ({
  rows = 5,
  label,
}) => (
  <div aria-busy="true" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
    <span className="visually-hidden">{label} is loading</span>
    {Array.from({ length: rows }).map((_, i) => (
      <div
        key={i}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '10px 12px',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-sm)',
          background: 'var(--its-bg-surface)',
        }}
      >
        <Skeleton width={8} height={8} radius="50%" />
        <Skeleton width="30%" height={12} />
        <Skeleton width="18%" height={12} />
        <div style={{ flex: 1 }} />
        <Skeleton width={72} height={16} radius="var(--radius-full)" />
      </div>
    ))}
  </div>
);
