import React, { useCallback, useEffect, useState } from 'react';
import { Gauge, HelpCircle, Lock, ShieldCheck, Unlock } from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';

/**
 * TRAFFICINTEL AI - Data-Quality Trust Score
 *
 * The operator's answer to "how much should I believe this screen?".
 *
 * Two rules drive the whole design:
 *
 *   1. UNRATED IS NOT ZERO. A junction with nothing attached renders as a
 *      dash, never as 0/100. Zero means "measured and bad"; a dash means
 *      "not measured". Painting an uninstrumented junction red would send
 *      crews to fix equipment that is working fine, and would make the
 *      network look like it is failing when it is simply not watched.
 *
 *   2. THE COMPOSITE IS NEVER SHOWN ALONE. A single 0-100 number is exactly
 *      the kind of unaccountable summary this platform exists to refuse, so
 *      every component and its weight is on screen beside it, and the
 *      weakest one is called out by name because that is the thing to fix.
 */

export type TrustBand = 'TRUSTED' | 'PARTIAL' | 'UNTRUSTED' | 'UNRATED';

export interface TrustComponent {
  name: string;
  label: string;
  weight: number;
  score: number | null;
  status: 'SCORED' | 'NOT_APPLICABLE' | 'NOT_CONFIGURED';
  explanation: string;
  observed: Record<string, unknown> | null;
}

export interface TrustResult {
  intersection_id: string;
  intersection_name?: string;
  score: number | null;
  band: TrustBand;
  window_minutes?: number;
  components: TrustComponent[];
  components_scored?: number;
  components_not_applicable?: number;
  weight_basis?: string;
  explanation?: string;
  weakest_component?: { name: string; score: number; explanation: string } | null;
  ai_gate?: { allowed: boolean; threshold: number; reason: string | null };
}

interface BandAppearance {
  color: string;
  background: string;
  border: string;
  label: string;
  meaning: string;
}

export function trustAppearance(band: TrustBand): BandAppearance {
  switch (band) {
    case 'TRUSTED':
      return {
        color: 'var(--its-status-normal)',
        background: 'var(--its-status-normal-bg, rgba(34,197,94,0.10))',
        border: 'var(--its-status-normal)',
        label: 'TRUSTED',
        meaning: 'Sources are connected and current. Readings can be acted on directly.',
      };
    case 'PARTIAL':
      return {
        color: 'var(--its-status-warning)',
        background: 'var(--its-status-warning-bg, rgba(234,179,8,0.10))',
        border: 'var(--its-status-warning)',
        label: 'PARTIAL',
        meaning: 'Some sources are degraded. Confirm against another source before acting.',
      };
    case 'UNTRUSTED':
      return {
        color: 'var(--its-status-critical)',
        background: 'var(--its-status-critical-bg, rgba(239,68,68,0.10))',
        border: 'var(--its-status-critical)',
        label: 'UNTRUSTED',
        meaning: 'Measured, and measured badly. Treat figures here as unreliable.',
      };
    default:
      return {
        color: 'var(--its-text-muted)',
        background: 'transparent',
        border: 'var(--its-border-subtle)',
        label: 'UNRATED',
        meaning: 'Not enough is measured here to rate. This is not the same as a bad score.',
      };
  }
}

/** The score as text. A dash for UNRATED - never the digit zero. */
export function trustScoreText(result: { score: number | null; band: TrustBand }): string {
  if (result.score === null || result.band === 'UNRATED') return '--';
  return String(Math.round(result.score));
}

/** Compact badge for lists, map popups and page headers. */
export const TrustBadge: React.FC<{
  band: TrustBand;
  score: number | null;
  size?: 'sm' | 'md';
  showLabel?: boolean;
}> = ({ band, score, size = 'sm', showLabel = true }) => {
  const look = trustAppearance(band);
  const unrated = score === null || band === 'UNRATED';

  return (
    <span
      title={look.meaning}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        padding: size === 'sm' ? '2px 7px' : '4px 10px',
        borderRadius: 'var(--radius-sm)',
        border: `1px solid ${look.border}`,
        background: look.background,
        color: look.color,
        fontSize: size === 'sm' ? '10px' : '11px',
        fontWeight: 700,
        letterSpacing: '0.04em',
        whiteSpace: 'nowrap',
      }}
    >
      {unrated ? <HelpCircle size={size === 'sm' ? 11 : 13} /> : <Gauge size={size === 'sm' ? 11 : 13} />}
      <span className="mono">{trustScoreText({ score, band })}</span>
      {showLabel && <span>{look.label}</span>}
    </span>
  );
};

/** A single component row with its weight and contribution. */
const ComponentRow: React.FC<{ component: TrustComponent; isWeakest: boolean }> = ({
  component,
  isWeakest,
}) => {
  const scored = component.status === 'SCORED' && component.score !== null;
  const score = component.score ?? 0;
  const barColor = !scored
    ? 'var(--its-border-subtle)'
    : score >= 80
      ? 'var(--its-status-normal)'
      : score >= 60
        ? 'var(--its-status-warning)'
        : 'var(--its-status-critical)';

  return (
    <div
      style={{
        padding: '9px 10px',
        borderBottom: '1px solid var(--its-border-subtle)',
        background: isWeakest ? 'var(--its-bg-elevated)' : 'transparent',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
        <span style={{ fontSize: '11px', fontWeight: 600, flex: 1 }}>
          {component.label}
          {isWeakest && (
            <span
              style={{
                marginLeft: '6px',
                fontSize: '9px',
                fontWeight: 700,
                color: 'var(--its-status-warning)',
                letterSpacing: '0.05em',
              }}
            >
              LIMITING FACTOR
            </span>
          )}
        </span>
        <span
          className="mono"
          style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}
          title="Share of the composite score, renormalised across scorable components."
        >
          w {(component.weight * 100).toFixed(0)}%
        </span>
        <span
          className="mono"
          style={{ fontSize: '12px', fontWeight: 700, color: barColor, minWidth: '34px', textAlign: 'right' }}
        >
          {scored ? score.toFixed(0) : '--'}
        </span>
      </div>

      {/* The bar is drawn only when there is a measurement. An empty track for
          an unmeasured component reads as "zero" at a glance. */}
      <div
        style={{
          height: '4px',
          marginTop: '5px',
          borderRadius: '2px',
          background: 'var(--its-bg-base)',
          overflow: 'hidden',
        }}
      >
        {scored ? (
          <div style={{ width: `${score}%`, height: '100%', background: barColor }} />
        ) : (
          <div
            style={{
              height: '100%',
              backgroundImage:
                'repeating-linear-gradient(45deg, var(--its-border-subtle) 0 3px, transparent 3px 6px)',
            }}
          />
        )}
      </div>

      <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '5px', lineHeight: 1.5 }}>
        {component.status !== 'SCORED' && (
          <strong style={{ color: 'var(--its-text-secondary)' }}>{component.status.replace(/_/g, ' ')}: </strong>
        )}
        {component.explanation}
      </div>
    </div>
  );
};

/**
 * Full trust breakdown. Used on the junction drawer and the trust page.
 * Pass `result` to render a score already fetched; pass `intersectionId` to
 * have the panel fetch it itself.
 */
export const TrustPanel: React.FC<{
  intersectionId?: string;
  result?: TrustResult | null;
  windowMinutes?: number;
  compact?: boolean;
}> = ({ intersectionId, result: provided, windowMinutes = 60, compact = false }) => {
  const [result, setResult] = useState<TrustResult | null>(provided ?? null);
  const [loading, setLoading] = useState(!provided && !!intersectionId);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!intersectionId) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.getJunctionTrust(intersectionId, windowMinutes));
    } catch (e: any) {
      setError(e?.message || 'Trust score could not be retrieved.');
    } finally {
      setLoading(false);
    }
  }, [intersectionId, windowMinutes]);

  useEffect(() => {
    if (provided) {
      setResult(provided);
      setLoading(false);
      return;
    }
    void load();
  }, [provided, load]);

  if (loading) return <SkeletonRows rows={5} label="Assessing data quality" />;

  if (error) {
    return (
      <div className="its-panel" style={{ padding: '12px', fontSize: '11px', color: 'var(--its-status-critical)' }}>
        TRUST SCORE UNAVAILABLE - {error}
        <button className="its-btn its-btn-sm" style={{ marginLeft: '10px' }} onClick={() => void load()}>
          Retry
        </button>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="its-panel" style={{ padding: '12px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
        NO TRUST ASSESSMENT AVAILABLE - select a junction to assess its data quality.
      </div>
    );
  }

  const look = trustAppearance(result.band);
  const unrated = result.score === null || result.band === 'UNRATED';
  const gate = result.ai_gate;

  return (
    <div className="its-panel">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '14px',
          padding: '14px',
          borderBottom: '1px solid var(--its-border-subtle)',
          background: look.background,
        }}
      >
        <div
          style={{
            width: '62px',
            height: '62px',
            borderRadius: '50%',
            border: `2px solid ${look.border}`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <span
            className="mono"
            style={{ fontSize: unrated ? '20px' : '22px', fontWeight: 800, color: look.color, lineHeight: 1 }}
          >
            {trustScoreText(result)}
          </span>
          {!unrated && (
            <span style={{ fontSize: '8px', color: 'var(--its-text-muted)', marginTop: '2px' }}>/ 100</span>
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '13px', fontWeight: 700, color: look.color, letterSpacing: '0.04em' }}>
            {look.label}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '3px', lineHeight: 1.5 }}>
            {look.meaning}
          </div>
          {result.window_minutes != null && (
            <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
              Assessed over the last {result.window_minutes} min.
            </div>
          )}
        </div>
      </div>

      {unrated && result.explanation && (
        <div
          style={{
            padding: '10px 14px',
            fontSize: '10px',
            lineHeight: 1.6,
            color: 'var(--its-text-secondary)',
            borderBottom: '1px solid var(--its-border-subtle)',
          }}
        >
          {result.explanation}
        </div>
      )}

      {/* The AI gate is stated in the operator's terms: what is withheld, why,
          and what to do instead. */}
      {gate && (
        <div
          style={{
            display: 'flex',
            gap: '9px',
            padding: '10px 14px',
            borderBottom: '1px solid var(--its-border-subtle)',
            background: gate.allowed ? 'transparent' : 'var(--its-bg-elevated)',
          }}
        >
          {gate.allowed ? (
            <Unlock size={14} style={{ color: 'var(--its-status-normal)', flexShrink: 0, marginTop: '1px' }} />
          ) : (
            <Lock size={14} style={{ color: 'var(--its-status-warning)', flexShrink: 0, marginTop: '1px' }} />
          )}
          <div style={{ fontSize: '10px', lineHeight: 1.6 }}>
            <strong style={{ color: gate.allowed ? 'var(--its-status-normal)' : 'var(--its-status-warning)' }}>
              {gate.allowed
                ? `AI RECOMMENDATIONS ENABLED (threshold ${gate.threshold})`
                : `AI RECOMMENDATIONS WITHHELD (threshold ${gate.threshold})`}
            </strong>
            <div style={{ color: 'var(--its-text-muted)', marginTop: '3px' }}>
              {gate.reason ||
                'Data quality meets the threshold for computed recommendations at this junction.'}
            </div>
            {!gate.allowed && (
              <div style={{ color: 'var(--its-text-secondary)', marginTop: '4px' }}>
                Operator-entered volumes are never gated - the optimiser will run on figures you
                type in, because those are your own assertion rather than a stale reading.
              </div>
            )}
          </div>
        </div>
      )}

      {!compact && (
        <>
          <div
            style={{
              padding: '8px 14px',
              fontSize: '9px',
              fontWeight: 700,
              letterSpacing: '0.08em',
              color: 'var(--its-text-muted)',
              borderBottom: '1px solid var(--its-border-subtle)',
            }}
          >
            COMPONENTS ({result.components_scored ?? 0} SCORED
            {result.components_not_applicable ? `, ${result.components_not_applicable} NOT ASSESSABLE` : ''})
          </div>

          {result.components.map((component) => (
            <ComponentRow
              key={component.name}
              component={component}
              isWeakest={result.weakest_component?.name === component.name}
            />
          ))}

          {result.weight_basis && (
            <div
              style={{
                padding: '9px 14px',
                fontSize: '9px',
                color: 'var(--its-text-muted)',
                lineHeight: 1.6,
                display: 'flex',
                gap: '7px',
              }}
            >
              <ShieldCheck size={12} style={{ flexShrink: 0, marginTop: '1px' }} />
              <span>{result.weight_basis}</span>
            </div>
          )}
        </>
      )}
    </div>
  );
};
