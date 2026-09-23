import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, HelpCircle, Play, Plus, Send, Trash2, X,
} from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { useTickingAge } from '../hooks/useTickingAge';
import { formatAge, formatTimestamp } from '../lib/quality';
import { useConsole } from '../context/ConsoleContext';

/**
 * TRAFFICINTEL AI - Alert Rules
 *
 * Operator-defined rules over real stored state.
 *
 * The evaluation view gives INSUFFICIENT_DATA its own visual treatment, level
 * with MATCHED rather than below it. A rule that cannot be evaluated is not a
 * quiet pass: it usually means a detector was configured and never connected,
 * which is the finding the operator most needs and the one a naive UI buries.
 */

const OUTCOME_STYLE: Record<string, { color: string; bg: string; label: string; meaning: string }> = {
  MATCHED: {
    color: 'var(--its-signal-red)', bg: 'var(--its-signal-red-bg)',
    label: 'MATCHED', meaning: 'The condition is true right now.',
  },
  NOT_MATCHED: {
    color: 'var(--its-signal-green)', bg: 'var(--its-signal-green-bg)',
    label: 'NOT MATCHED', meaning: 'Measured, and the condition is false.',
  },
  INSUFFICIENT_DATA: {
    color: 'var(--its-signal-yellow)', bg: 'var(--its-signal-yellow-bg)',
    label: 'INSUFFICIENT DATA',
    meaning: 'The condition could not be evaluated. This is not a pass.',
  },
  SUPPRESSED_COOLDOWN: {
    color: 'var(--its-text-muted)', bg: 'var(--its-stale-bg)',
    label: 'SUPPRESSED (COOLDOWN)',
    meaning: 'Matched, but an unacknowledged alert already exists.',
  },
  SUPPRESSED_DUPLICATE: {
    color: 'var(--its-text-muted)', bg: 'var(--its-stale-bg)',
    label: 'SUPPRESSED (DUPLICATE)',
    meaning: 'Matched, and folded into the existing alert.',
  },
};

const EvaluationRow: React.FC<{ result: any }> = ({ result }) => {
  const style = OUTCOME_STYLE[result.outcome] ?? OUTCOME_STYLE.NOT_MATCHED;
  return (
    <div
      style={{
        display: 'flex', gap: '10px', padding: '9px 11px',
        borderRadius: 'var(--radius-sm)', background: style.bg,
        border: `1px solid ${style.color}33`,
      }}
    >
      <span
        className="mono"
        style={{
          fontSize: '9px', fontWeight: 700, color: style.color,
          whiteSpace: 'nowrap', paddingTop: '2px',
        }}
        title={style.meaning}
      >
        {style.label}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--its-text-primary)' }}>
          {result.subject_label}
          <span style={{ color: 'var(--its-text-muted)', fontWeight: 400 }}>
            {' '}· {result.subject_type}
          </span>
        </div>
        <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '3px', lineHeight: 1.5 }}>
          {result.explanation}
        </div>
        {result.observed && Object.keys(result.observed).length > 0 && (
          <details style={{ marginTop: '5px' }}>
            <summary style={{ fontSize: '10px', color: 'var(--its-text-muted)', cursor: 'pointer' }}>
              Values the rule saw
            </summary>
            <pre
              className="mono"
              style={{
                fontSize: '10px', color: 'var(--its-text-secondary)', marginTop: '4px',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}
            >
              {JSON.stringify(result.observed, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </div>
  );
};

const RuleRow: React.FC<{
  rule: any;
  onEvaluate: (rule: any, dryRun: boolean) => void;
  onDelete: (rule: any) => void;
  busy: boolean;
}> = ({ rule, onEvaluate, onDelete, busy }) => {
  const lastFiredAge = useTickingAge(rule.last_fired_at);
  const lastEvalAge = useTickingAge(rule.last_evaluated_at);

  return (
    <div className="its-card">
      <div className="its-card-header">
        <span className="its-card-title">
          <AlertTriangle
            size={14}
            color={rule.enabled ? 'var(--its-signal-yellow)' : 'var(--its-text-muted)'}
          />
          <span>{rule.name}</span>
        </span>
        <span
          className="mono"
          style={{
            fontSize: '10px', padding: '2px 7px', borderRadius: 'var(--radius-full)',
            background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)',
            color: rule.severity === 'CRITICAL' ? 'var(--its-signal-red)' : 'var(--its-text-secondary)',
          }}
        >
          {rule.severity}
        </span>
      </div>

      <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.6 }}>
        <span className="mono">{rule.condition_type}</span>
        {' · '}
        <span className="mono">{JSON.stringify(rule.parameters)}</span>
      </div>

      <div
        className="mono"
        style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '8px' }}
      >
        {rule.enabled ? 'ENABLED' : 'DISABLED'}
        {' · COOLDOWN '}{rule.cooldown_sec}s
        {rule.escalate_after_sec ? ` · ESCALATES AFTER ${rule.escalate_after_sec}s` : ''}
        {' · CHANNELS '}{(rule.delivery_channels ?? []).join(', ') || 'NONE'}
      </div>

      <div
        className="mono"
        style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}
        title={formatTimestamp(rule.last_fired_at)}
      >
        FIRED {rule.fire_count}x
        {rule.last_fired_at ? ` · LAST ${formatAge(lastFiredAge)} AGO` : ' · NEVER'}
        {rule.last_evaluated_at ? ` · EVALUATED ${formatAge(lastEvalAge)} AGO` : ' · NOT YET EVALUATED'}
      </div>

      <div style={{ display: 'flex', gap: '6px', marginTop: '12px', flexWrap: 'wrap' }}>
        <button
          onClick={() => onEvaluate(rule, true)}
          className="its-btn"
          disabled={busy}
          style={{ padding: '3px 9px' }}
          title="Evaluate against current state. Raises nothing, writes nothing."
        >
          <Play size={11} />
          <span>Dry run</span>
        </button>
        <button
          onClick={() => onEvaluate(rule, false)}
          className="its-btn"
          disabled={busy}
          style={{ padding: '3px 9px' }}
          title="Evaluate and raise alerts for anything that matches."
        >
          <Send size={11} />
          <span>Evaluate & alert</span>
        </button>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => onDelete(rule)}
          className="its-btn its-btn-danger"
          disabled={busy}
          style={{ padding: '3px 9px' }}
        >
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  );
};

export const AlertRules: React.FC = () => {
  const [rules, setRules] = useState<any[]>([]);
  const [conditionTypes, setConditionTypes] = useState<any[]>([]);
  const [intersections, setIntersections] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [showCreate, setShowCreate] = useState(false);
  const { notify } = useConsole();

  // Create form
  const [name, setName] = useState('');
  const [conditionType, setConditionType] = useState('DETECTOR_SILENT');
  const [parameters, setParameters] = useState('{"silent_for_sec": 60}');
  const [severity, setSeverity] = useState('WARNING');
  const [cooldown, setCooldown] = useState(300);
  const [intersectionId, setIntersectionId] = useState('');
  const [channels, setChannels] = useState<string[]>(['UI']);
  const [webhookUrl, setWebhookUrl] = useState('');
  const [emailTo, setEmailTo] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ruleList, types, inters] = await Promise.all([
        api.getRules(),
        api.getRuleConditionTypes(),
        api.getIntersections().catch(() => []),
      ]);
      setRules(ruleList);
      setConditionTypes(types.condition_types ?? []);
      setIntersections(inters);
    } catch (err: any) {
      setError(err.message || 'Could not load alert rules');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedType = useMemo(
    () => conditionTypes.find(t => t.type === conditionType),
    [conditionTypes, conditionType],
  );

  const evaluate = async (rule: any, dryRun: boolean) => {
    setBusy(true);
    setEvaluation(null);
    try {
      const result = await api.evaluateRule(rule.id, dryRun);
      setEvaluation({ ...result, dry_run: dryRun });
      if (!dryRun && result.matched > 0) {
        notify({
          severity: 'WARNING',
          title: `${rule.name}: ${result.matched} match(es)`,
          detail: 'Alerts raised from real stored state.',
          origin: 'operator.action',
          link: '/incidents',
        });
      }
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (rule: any) => {
    setBusy(true);
    try {
      await api.deleteRule(rule.id);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      let parsed: any;
      try {
        parsed = JSON.parse(parameters);
      } catch {
        setError('Parameters must be valid JSON.');
        setBusy(false);
        return;
      }
      await api.createRule({
        name,
        condition_type: conditionType,
        parameters: parsed,
        severity,
        cooldown_sec: cooldown,
        intersection_id: intersectionId || null,
        delivery_channels: channels,
        webhook_url: webhookUrl || null,
        email_to: emailTo || null,
      });
      setShowCreate(false);
      setName('');
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">
            <AlertTriangle size={14} color="var(--its-text-accent)" />
            <span>Alert Rules</span>
          </span>
          <button onClick={() => setShowCreate(true)} className="its-btn its-btn-primary" style={{ padding: '3px 9px' }}>
            <Plus size={12} />
            <span>New rule</span>
          </button>
        </div>

        <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.7 }}>
          Rules evaluate against real stored state only. A condition that cannot be
          evaluated returns <strong>INSUFFICIENT DATA</strong>, never a silent pass —
          a detector that was configured and never connected is a finding, not a
          clean check.
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="its-card"
          style={{ borderColor: 'var(--its-signal-red-border)', background: 'var(--its-signal-red-bg)' }}
        >
          <strong>RULE OPERATION FAILED</strong>
          <div style={{ fontSize: 'var(--text-2xs)', marginTop: '4px' }}>{error}</div>
        </div>
      )}

      {/* Evaluation result ------------------------------------------------ */}
      {evaluation && (
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              {evaluation.dry_run ? <Play size={14} /> : <Send size={14} />}
              <span>
                {evaluation.dry_run ? 'Dry run' : 'Evaluation'}: {evaluation.rule_name}
              </span>
            </span>
            <button
              onClick={() => setEvaluation(null)}
              className="its-btn"
              style={{ padding: '2px 7px' }}
              aria-label="Close evaluation"
            >
              <X size={11} />
            </button>
          </div>

          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '10px' }}>
            {[
              ['Subjects evaluated', evaluation.subjects_evaluated],
              ['Matched', evaluation.matched],
              ['Insufficient data', evaluation.insufficient_data],
            ].map(([label, value]) => (
              <div key={String(label)} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="mono" style={{ fontWeight: 700 }}>{String(value)}</span>
                <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}>
                  {label}
                </span>
              </div>
            ))}
            {evaluation.dry_run && (
              <span
                className="mono"
                style={{ fontSize: '10px', color: 'var(--its-text-accent)', fontWeight: 700 }}
              >
                NOTHING WAS RAISED OR WRITTEN
              </span>
            )}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {(evaluation.results ?? []).map((result: any, i: number) => (
              <EvaluationRow key={i} result={result} />
            ))}
            {(evaluation.results ?? []).length === 0 && (
              <div className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>
                NO SUBJECTS MATCHED THIS RULE'S SCOPE
              </div>
            )}
          </div>
        </div>
      )}

      {/* Rules ------------------------------------------------------------ */}
      {loading ? (
        <SkeletonRows rows={3} label="Alert rules" />
      ) : rules.length === 0 ? (
        <div className="its-card">
          <div className="mono" style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}>
            NO ALERT RULES CONFIGURED
          </div>
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '8px', lineHeight: 1.6 }}>
            Rules are how the platform tells an operator something changed without
            them watching for it. Nothing is evaluated until you define one.
          </div>
        </div>
      ) : (
        <div className="grid-2">
          {rules.map(rule => (
            <RuleRow
              key={rule.id}
              rule={rule}
              onEvaluate={evaluate}
              onDelete={remove}
              busy={busy}
            />
          ))}
        </div>
      )}

      {/* Create drawer ---------------------------------------------------- */}
      {showCreate && (
        <>
          <div className="drawer-backdrop" onClick={() => setShowCreate(false)} />
          <aside className="junction-drawer" role="dialog" aria-modal="true" aria-label="New alert rule">
            <div className="drawer-header">
              <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>NEW ALERT RULE</span>
              <button
                onClick={() => setShowCreate(false)}
                aria-label="Close"
                style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--its-text-muted)' }}
              >
                <X size={17} />
              </button>
            </div>

            <div className="junction-drawer-body">
              <label style={fieldLabel} htmlFor="rule-name">Rule name</label>
              <input id="rule-name" className="its-input" value={name} onChange={e => setName(e.target.value)} placeholder="Detector silent > 60s" />

              <label style={fieldLabel} htmlFor="rule-type">Condition</label>
              <select
                id="rule-type"
                className="its-select"
                value={conditionType}
                onChange={e => {
                  setConditionType(e.target.value);
                  const type = conditionTypes.find(t => t.type === e.target.value);
                  const template: Record<string, any> = {};
                  Object.keys(type?.parameters ?? {}).forEach(key => { template[key] = null; });
                  setParameters(JSON.stringify(template, null, 2));
                }}
              >
                {conditionTypes.map(type => (
                  <option key={type.type} value={type.type}>{type.label}</option>
                ))}
              </select>

              {selectedType && (
                <div
                  style={{
                    padding: '9px 11px', borderRadius: 'var(--radius-sm)',
                    background: 'var(--its-bg-subsurface)', fontSize: 'var(--text-2xs)',
                    color: 'var(--its-text-secondary)', lineHeight: 1.6,
                  }}
                >
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                    <HelpCircle size={12} style={{ marginTop: 2, flexShrink: 0 }} />
                    <div>
                      {selectedType.description}
                      <ul style={{ margin: '6px 0 0', paddingLeft: '16px' }}>
                        {Object.entries(selectedType.parameters ?? {}).map(([key, help]) => (
                          <li key={key}>
                            <span className="mono">{key}</span> — {String(help)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}

              <label style={fieldLabel} htmlFor="rule-params">Parameters (JSON)</label>
              <textarea
                id="rule-params"
                className="its-input"
                rows={4}
                value={parameters}
                onChange={e => setParameters(e.target.value)}
                style={{ fontFamily: 'var(--font-mono)', resize: 'vertical' }}
              />

              <label style={fieldLabel} htmlFor="rule-scope">Scope</label>
              <select id="rule-scope" className="its-select" value={intersectionId} onChange={e => setIntersectionId(e.target.value)}>
                <option value="">Whole network</option>
                {intersections.map(inter => (
                  <option key={inter.id} value={inter.id}>{inter.name}</option>
                ))}
              </select>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={fieldLabel} htmlFor="rule-sev">Severity</label>
                  <select id="rule-sev" className="its-select" value={severity} onChange={e => setSeverity(e.target.value)}>
                    <option value="INFO">INFO</option>
                    <option value="WARNING">WARNING</option>
                    <option value="CRITICAL">CRITICAL</option>
                  </select>
                </div>
                <div>
                  <label style={fieldLabel} htmlFor="rule-cd">Cooldown (s)</label>
                  <input
                    id="rule-cd"
                    type="number"
                    className="its-input"
                    value={cooldown}
                    onChange={e => setCooldown(Number(e.target.value))}
                  />
                </div>
              </div>

              <label style={fieldLabel}>Delivery channels</label>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                {['UI', 'WEBHOOK', 'EMAIL'].map(channel => (
                  <label key={channel} style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: 'var(--text-2xs)' }}>
                    <input
                      type="checkbox"
                      checked={channels.includes(channel)}
                      onChange={() =>
                        setChannels(prev =>
                          prev.includes(channel)
                            ? prev.filter(c => c !== channel)
                            : [...prev, channel])
                      }
                      style={{ accentColor: 'var(--its-text-accent)' }}
                    />
                    {channel}
                  </label>
                ))}
              </div>

              {channels.includes('WEBHOOK') && (
                <>
                  <label style={fieldLabel} htmlFor="rule-hook">Webhook URL</label>
                  <input id="rule-hook" className="its-input" value={webhookUrl} onChange={e => setWebhookUrl(e.target.value)} placeholder="https://ops.example.gov/hooks/traffic" />
                </>
              )}

              {channels.includes('EMAIL') && (
                <>
                  <label style={fieldLabel} htmlFor="rule-email">Email recipients</label>
                  <input id="rule-email" className="its-input" value={emailTo} onChange={e => setEmailTo(e.target.value)} placeholder="ops@example.gov" />
                  <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', lineHeight: 1.5 }}>
                    With no SMTP host configured on this deployment, email delivery is
                    recorded as SKIPPED_NOT_CONFIGURED rather than reported as sent.
                  </div>
                </>
              )}

              <button
                onClick={create}
                className="its-btn its-btn-primary"
                disabled={busy || !name}
                style={{ justifyContent: 'center', marginTop: '6px' }}
              >
                <CheckCircle2 size={13} />
                <span>Create rule</span>
              </button>
            </div>
          </aside>
        </>
      )}
    </div>
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
