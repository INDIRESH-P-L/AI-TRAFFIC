import React from 'react';
import { Brain, HelpCircle, ShieldCheck, ShieldX, TrendingUp, XCircle } from 'lucide-react';
import { ProvenanceChip } from './provenance/Provenance';
import { normalizeQuality } from '../lib/quality';
import type { QualityThresholds } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Explainable AI recommendation panel
 *
 * Renders an AI recommendation as an argument the operator can audit rather
 * than a verdict they must trust:
 *
 *   - every input used, with its own data-quality state
 *   - what data was MISSING, which is usually the more important half
 *   - the confidence and expected effect, with uncertainty
 *   - the Safety Engine's verdict on the proposal
 *
 * A recommendation is never shown as actionable unless it passed the Safety
 * Engine, and the panel states which inputs were stale, because a confident
 * recommendation computed from stale detectors is a confident guess.
 */

export interface AiInput {
  name: string;
  value: string | number | null;
  unit?: string;
  quality: string;
  observed_at?: string | null;
  source?: string | null;
}

export interface AiRecommendation {
  model_version: string;
  action: string;
  rationale: string;
  confidence: number | null;
  expected_effect?: {
    metric: string;
    change: number | null;
    unit?: string;
    uncertainty?: string | null;
  } | null;
  inputs: AiInput[];
  missing_inputs: string[];
  safety_verdict?: {
    is_safe: boolean;
    violations: string[];
  } | null;
  evaluated_at?: string | null;
}

interface Props {
  recommendation: AiRecommendation | null;
  loading?: boolean;
  /** Why no recommendation exists. Shown verbatim — this is the common case. */
  unavailableReason?: string | null;
  thresholds?: QualityThresholds;
  onApply?: (recommendation: AiRecommendation) => void;
}

export const ExplainableAiPanel: React.FC<Props> = ({
  recommendation,
  loading = false,
  unavailableReason,
  thresholds,
  onApply,
}) => {
  // --- Not configured / no recommendation --------------------------------
  if (!loading && !recommendation) {
    return (
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <Brain size={14} color="var(--its-text-indigo)" />
            <span>AI Recommendation</span>
          </span>
        </div>

        <div style={{ padding: '20px 4px' }}>
          <div style={emptyText}>
            {unavailableReason ?? 'NO AI RECOMMENDATION AVAILABLE'}
          </div>
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '8px', lineHeight: 1.6 }}>
            The optimiser produces a recommendation only from real detector data or
            operator-entered volumes. With no measured demand for this junction there is
            nothing to optimise against, and no proposal is generated.
          </div>
        </div>
      </div>
    );
  }

  if (loading || !recommendation) {
    return (
      <div className="its-card" aria-busy="true">
        <div className="its-card-header">
          <span className="its-card-title">
            <Brain size={14} color="var(--its-text-indigo)" />
            <span>AI Recommendation</span>
          </span>
        </div>
        <div className="skeleton" style={{ height: 18, marginBottom: 10 }} />
        <div className="skeleton" style={{ height: 52 }} />
      </div>
    );
  }

  const safe = recommendation.safety_verdict?.is_safe === true;
  const hasSafetyVerdict = recommendation.safety_verdict != null;

  // Inputs whose quality is anything but FRESH weaken the whole recommendation.
  const degradedInputs = recommendation.inputs.filter(
    input => normalizeQuality(input.quality) !== 'FRESH',
  );

  return (
    <div className="its-card">
      <div className="its-card-header">
        <span className="its-card-title">
          <Brain size={14} color="var(--its-text-indigo)" />
          <span>AI Recommendation</span>
        </span>
        <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
          {recommendation.model_version}
        </span>
      </div>

      {/* Proposed action */}
      <div
        style={{
          padding: '10px 12px', borderRadius: 'var(--radius-md)',
          border: '1px solid var(--its-border-accent)', background: 'var(--its-fresh-bg)',
          marginBottom: '12px',
        }}
      >
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
          {recommendation.action}
        </div>
        <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
          {recommendation.rationale}
        </div>
      </div>

      {/* Confidence & expected effect */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
        <div>
          <div style={sectionLabel}>Confidence</div>
          <div className="mono" style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>
            {recommendation.confidence === null
              ? 'NOT STATED'
              : `${Math.round(recommendation.confidence * 100)}%`}
          </div>
        </div>

        <div>
          <div style={sectionLabel}>Expected effect</div>
          {recommendation.expected_effect?.change == null ? (
            <div className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>
              NOT ESTIMATED
            </div>
          ) : (
            <div>
              <span
                className="mono"
                style={{
                  fontSize: 'var(--text-md)', fontWeight: 700,
                  color: recommendation.expected_effect.change < 0
                    ? 'var(--its-signal-green)'
                    : 'var(--its-signal-yellow)',
                }}
              >
                {recommendation.expected_effect.change > 0 ? '+' : ''}
                {recommendation.expected_effect.change}
                {recommendation.expected_effect.unit ?? ''}
              </span>
              <div style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                {recommendation.expected_effect.metric}
                {recommendation.expected_effect.uncertainty && ` · ${recommendation.expected_effect.uncertainty}`}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Why this recommendation? */}
      <details open style={detailsStyle}>
        <summary style={summaryStyle}>
          <TrendingUp size={12} />
          <span>Why this recommendation?</span>
        </summary>

        <div style={{ paddingTop: '8px' }}>
          <div style={sectionLabel}>Inputs used ({recommendation.inputs.length})</div>

          {recommendation.inputs.length === 0 ? (
            <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}>
              No inputs were recorded for this recommendation.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', marginTop: '5px' }}>
              {recommendation.inputs.map(input => (
                <div
                  key={input.name}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    padding: '5px 8px', borderRadius: 'var(--radius-xs)',
                    background: 'var(--its-bg-subsurface)',
                  }}
                >
                  <span style={{ flex: 1, minWidth: 0, fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)' }}>
                    {input.name}
                  </span>
                  <span className="mono" style={{ fontSize: 'var(--text-2xs)', fontWeight: 700 }}>
                    {input.value === null ? 'NOT MEASURED' : `${input.value}${input.unit ?? ''}`}
                  </span>
                  <ProvenanceChip
                    provenance={{
                      state: normalizeQuality(input.quality),
                      age_sec: null,
                      observed_at: input.observed_at ?? null,
                      source: input.source ?? null,
                    }}
                    thresholds={thresholds}
                    compact
                  />
                </div>
              ))}
            </div>
          )}

          {degradedInputs.length > 0 && (
            <div style={warnBlock}>
              {degradedInputs.length} of {recommendation.inputs.length} inputs are not FRESH.
              Confidence is computed from the model, not from input quality, so treat this
              recommendation as weaker than its stated confidence suggests.
            </div>
          )}
        </div>
      </details>

      {/* What data is missing? */}
      <details style={detailsStyle}>
        <summary style={summaryStyle}>
          <HelpCircle size={12} />
          <span>What data is missing? ({recommendation.missing_inputs.length})</span>
        </summary>

        <div style={{ paddingTop: '8px' }}>
          {recommendation.missing_inputs.length === 0 ? (
            <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)' }}>
              Every input the model expects was available.
            </div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: '16px', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.8 }}>
              {recommendation.missing_inputs.map(name => (
                <li key={name}>
                  <span className="mono">{name}</span> — not reported by any connected source
                </li>
              ))}
            </ul>
          )}
        </div>
      </details>

      {/* Safety verdict */}
      <div
        style={{
          marginTop: '12px', padding: '10px 12px', borderRadius: 'var(--radius-md)',
          border: `1px solid ${
            !hasSafetyVerdict
              ? 'var(--its-border-subtle)'
              : safe ? 'var(--its-signal-green-border)' : 'var(--its-signal-red-border)'
          }`,
          background: !hasSafetyVerdict
            ? 'var(--its-bg-subsurface)'
            : safe ? 'var(--its-signal-green-bg)' : 'var(--its-signal-red-bg)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
          {!hasSafetyVerdict ? (
            <XCircle size={14} color="var(--its-text-muted)" />
          ) : safe ? (
            <ShieldCheck size={14} color="var(--its-signal-green)" />
          ) : (
            <ShieldX size={14} color="var(--its-signal-red)" />
          )}
          <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700 }}>
            {!hasSafetyVerdict
              ? 'SAFETY ENGINE: NOT YET EVALUATED'
              : safe
                ? 'SAFETY ENGINE: PROPOSAL PASSES'
                : 'SAFETY ENGINE: PROPOSAL REJECTED'}
          </span>
        </div>

        {recommendation.safety_verdict && recommendation.safety_verdict.violations.length > 0 && (
          <ul style={{ margin: '6px 0 0', paddingLeft: '18px', fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.6 }}>
            {recommendation.safety_verdict.violations.map((violation, i) => (
              <li key={i}>{violation}</li>
            ))}
          </ul>
        )}
      </div>

      {/* Applying still goes through the guided command workflow — an AI
          proposal gets no shortcut past the same validation an operator uses. */}
      {onApply && (
        <button
          onClick={() => onApply(recommendation)}
          className="its-btn its-btn-primary"
          disabled={!safe}
          title={safe ? 'Open the guided command workflow with this proposal' : 'Rejected proposals cannot be applied'}
          style={{ width: '100%', justifyContent: 'center', marginTop: '10px' }}
        >
          <ShieldCheck size={13} />
          <span>Review in command workflow</span>
        </button>
      )}
    </div>
  );
};

const sectionLabel: React.CSSProperties = {
  fontSize: '10px',
  fontWeight: 700,
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  color: 'var(--its-text-muted)',
  marginBottom: '3px',
};

const detailsStyle: React.CSSProperties = {
  borderTop: '1px solid var(--its-border-subtle)',
  paddingTop: '10px',
  marginTop: '10px',
};

const summaryStyle: React.CSSProperties = {
  cursor: 'pointer',
  fontSize: 'var(--text-xs)',
  fontWeight: 700,
  color: 'var(--its-text-primary)',
  display: 'flex',
  alignItems: 'center',
  gap: '7px',
  listStyle: 'none',
};

const warnBlock: React.CSSProperties = {
  marginTop: '8px',
  padding: '7px 10px',
  borderRadius: 'var(--radius-xs)',
  border: '1px solid var(--its-signal-yellow-border)',
  background: 'var(--its-signal-yellow-bg)',
  fontSize: 'var(--text-2xs)',
  color: 'var(--its-text-primary)',
  lineHeight: 1.5,
};

const emptyText: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 'var(--text-xs)',
  fontWeight: 700,
  color: 'var(--its-text-muted)',
  letterSpacing: '0.04em',
};
