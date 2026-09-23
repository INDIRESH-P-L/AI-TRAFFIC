import React, { useCallback, useEffect, useState } from 'react';
import {
  Copy, Download, Key, Link2, Plus, ShieldCheck, ShieldX, Trash2, X,
} from 'lucide-react';
import { api, getAuthToken } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { formatTimestamp } from '../lib/quality';
import { useConsole } from '../context/ConsoleContext';

/**
 * TRAFFICINTEL AI - Governance
 *
 * Audit explorer with live chain verification, the access model as data, and
 * scoped API key management.
 *
 * The chain banner is deliberately prominent and states what a hash chain does
 * and does not give you. A green "TAMPER-PROOF" badge would overclaim: the
 * chain makes tampering *detectable*, and the export exists so an agency can
 * anchor it somewhere its own DBA does not control.
 */

type Tab = 'AUDIT' | 'ACCESS' | 'KEYS';

export const Governance: React.FC = () => {
  const [tab, setTab] = useState<Tab>('AUDIT');
  const [verification, setVerification] = useState<any>(null);
  const [audit, setAudit] = useState<any>(null);
  const [scopes, setScopes] = useState<any>(null);
  const [keys, setKeys] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newKey, setNewKey] = useState<any>(null);
  const [showCreateKey, setShowCreateKey] = useState(false);
  const { notify } = useConsole();

  // Audit filters
  const [actionFilter, setActionFilter] = useState('');
  const [actorFilter, setActorFilter] = useState('');
  const [resultFilter, setResultFilter] = useState('');

  // Key form
  const [keyName, setKeyName] = useState('');
  const [keyScopes, setKeyScopes] = useState<string[]>(['telemetry:read']);
  const [expiresDays, setExpiresDays] = useState(90);

  const loadAudit = useCallback(async () => {
    const params = new URLSearchParams({ limit: '100' });
    if (actionFilter) params.set('action', actionFilter);
    if (actorFilter) params.set('actor', actorFilter);
    if (resultFilter) params.set('result', resultFilter);
    try {
      const [rows, chain] = await Promise.all([
        api.exploreAudit(params.toString()),
        api.verifyAuditChain(),
      ]);
      setAudit(rows);
      setVerification(chain);
    } catch (err: any) {
      setError(err.message);
    }
  }, [actionFilter, actorFilter, resultFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await loadAudit();
      const [scopeData, keyData] = await Promise.all([
        api.getScopes().catch(() => null),
        api.getApiKeys().catch(() => null),
      ]);
      setScopes(scopeData);
      setKeys(keyData);
    } finally {
      setLoading(false);
    }
  }, [loadAudit]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!loading) loadAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actionFilter, actorFilter, resultFilter]);

  const createKey = async () => {
    setError(null);
    try {
      const created = await api.createApiKey({
        name: keyName,
        scopes: keyScopes,
        expires_in_days: expiresDays,
      });
      setNewKey(created);
      setShowCreateKey(false);
      setKeyName('');
      load();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const revoke = async (id: string) => {
    try {
      await api.revokeApiKey(id);
      load();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const downloadExport = () => {
    // The export endpoint requires a bearer token, so it is fetched and saved
    // rather than linked: a plain anchor would arrive unauthenticated.
    fetch('/api/v1/governance/audit/export?download=true', {
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    })
      .then(response => response.blob())
      .then(blob => {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `trafficintel-audit-${new Date().toISOString().slice(0, 19)}.json`;
        anchor.click();
        URL.revokeObjectURL(url);
        notify({
          severity: 'INFO',
          title: 'Audit ledger exported',
          detail: 'Anchor this file outside the database to make tampering unrecoverable.',
          origin: 'operator.action',
        });
      })
      .catch(err => setError(err.message));
  };

  const chainIntact = verification?.status === 'INTACT';
  const chainEmpty = verification?.status === 'EMPTY';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* Chain status ----------------------------------------------------- */}
      <div
        className="its-card"
        style={{
          borderColor: chainIntact ? 'var(--its-signal-green-border)'
            : chainEmpty ? 'var(--its-border-default)' : 'var(--its-signal-red-border)',
          background: chainIntact ? 'var(--its-signal-green-bg)'
            : chainEmpty ? undefined : 'var(--its-signal-red-bg)',
        }}
      >
        <div className="its-card-header">
          <span className="its-card-title">
            {chainIntact
              ? <ShieldCheck size={14} color="var(--its-signal-green)" />
              : <ShieldX size={14} color={chainEmpty ? 'var(--its-text-muted)' : 'var(--its-signal-red)'} />}
            <span>Audit Ledger Integrity</span>
          </span>
          <button onClick={downloadExport} className="its-btn" style={{ padding: '3px 9px' }}>
            <Download size={12} />
            <span>Export chain</span>
          </button>
        </div>

        {verification ? (
          <>
            <div className="mono" style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>
              {verification.status}
              {verification.break_type ? ` — ${verification.break_type}` : ''}
            </div>
            <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '6px', lineHeight: 1.6 }}>
              {verification.detail}
            </div>
            {verification.entries_verified > 0 && (
              <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '6px' }}>
                {verification.entries_verified} ENTRIES VERIFIED
                {verification.chain_tip_hash ? ` · TIP ${verification.chain_tip_hash.slice(0, 16)}…` : ''}
              </div>
            )}
            {/* What this does and does not guarantee, stated rather than implied. */}
            <div
              style={{
                fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px',
                paddingTop: '10px', borderTop: '1px solid var(--its-border-subtle)', lineHeight: 1.6,
              }}
            >
              {verification.tamper_evidence_note}
            </div>
          </>
        ) : (
          <SkeletonRows rows={1} label="Chain verification" />
        )}
      </div>

      {/* Tabs ------------------------------------------------------------- */}
      <div style={{ display: 'flex', gap: '6px' }}>
        {(['AUDIT', 'ACCESS', 'KEYS'] as Tab[]).map(option => (
          <button
            key={option}
            onClick={() => setTab(option)}
            className="its-btn"
            aria-pressed={tab === option}
            style={{
              borderColor: tab === option ? 'var(--its-border-focused)' : undefined,
              color: tab === option ? 'var(--its-text-accent)' : undefined,
            }}
          >
            {option === 'AUDIT' ? <Link2 size={12} /> : option === 'KEYS' ? <Key size={12} /> : <ShieldCheck size={12} />}
            <span>{option === 'ACCESS' ? 'ACCESS MODEL' : option}</span>
          </button>
        ))}
      </div>

      {error && (
        <div
          role="alert"
          className="its-card"
          style={{ borderColor: 'var(--its-signal-red-border)', background: 'var(--its-signal-red-bg)' }}
        >
          <strong>GOVERNANCE OPERATION FAILED</strong>
          <div style={{ fontSize: 'var(--text-2xs)', marginTop: '4px' }}>{error}</div>
        </div>
      )}

      {/* Newly issued key ------------------------------------------------- */}
      {newKey && (
        <div
          className="its-card"
          style={{ borderColor: 'var(--its-signal-yellow-border)', background: 'var(--its-signal-yellow-bg)' }}
        >
          <div className="its-card-header">
            <span className="its-card-title">
              <Key size={14} color="var(--its-signal-yellow)" />
              <span>API key issued — shown once</span>
            </span>
            <button onClick={() => setNewKey(null)} className="its-btn" style={{ padding: '2px 7px' }} aria-label="Dismiss">
              <X size={11} />
            </button>
          </div>
          <div
            className="mono"
            style={{
              padding: '10px 12px', background: 'var(--its-bg-elevated)',
              border: '1px solid var(--its-border-default)', borderRadius: 'var(--radius-sm)',
              fontSize: 'var(--text-xs)', wordBreak: 'break-all', userSelect: 'all',
            }}
          >
            {newKey.api_key}
          </div>
          <button
            onClick={() => navigator.clipboard?.writeText(newKey.api_key)}
            className="its-btn"
            style={{ marginTop: '8px', padding: '3px 9px' }}
          >
            <Copy size={11} />
            <span>Copy</span>
          </button>
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-primary)', marginTop: '8px', lineHeight: 1.6 }}>
            {newKey.warning}
          </div>
        </div>
      )}

      {/* AUDIT ------------------------------------------------------------ */}
      {tab === 'AUDIT' && (
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">Audit Explorer</span>
            {audit && (
              <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                {audit.returned} OF {audit.total_matching}
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px,1fr))', gap: '8px', marginBottom: '12px' }}>
            <input className="its-input" placeholder="Filter by action" value={actionFilter} onChange={e => setActionFilter(e.target.value)} aria-label="Filter by action" />
            <input className="its-input" placeholder="Filter by actor" value={actorFilter} onChange={e => setActorFilter(e.target.value)} aria-label="Filter by actor" />
            <select className="its-select" value={resultFilter} onChange={e => setResultFilter(e.target.value)} aria-label="Filter by result">
              <option value="">Any result</option>
              <option value="EXECUTED">EXECUTED</option>
              <option value="REJECTED">REJECTED</option>
              <option value="FAILED">FAILED</option>
              <option value="VALIDATED">VALIDATED</option>
            </select>
          </div>

          {audit?.chain?.unchained_legacy_entries > 0 && (
            <div
              style={{
                padding: '9px 11px', borderRadius: 'var(--radius-sm)', marginBottom: '10px',
                border: '1px solid var(--its-signal-yellow-border)',
                background: 'var(--its-signal-yellow-bg)', fontSize: 'var(--text-2xs)', lineHeight: 1.6,
              }}
            >
              {audit.chain.note}
            </div>
          )}

          {loading && !audit ? (
            <SkeletonRows rows={6} label="Audit entries" />
          ) : !audit || audit.entries.length === 0 ? (
            <div className="mono" style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}>
              {audit?.empty_reason ?? 'NO_AUDIT_ENTRIES'}
            </div>
          ) : (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th style={{ width: '54px' }}>Seq</th>
                    <th>Timestamp</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Resource</th>
                    <th>Result</th>
                    <th>Hash</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.entries.map((entry: any) => (
                    <tr key={entry.id}>
                      <td className="mono">{entry.sequence ?? '—'}</td>
                      <td className="mono" style={{ fontSize: '10px' }}>
                        {formatTimestamp(entry.timestamp)}
                      </td>
                      <td>{entry.actor_username}</td>
                      <td className="mono" style={{ fontSize: '10px' }}>{entry.action}</td>
                      <td style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                        {entry.resource_type}
                      </td>
                      <td>
                        <span
                          className="mono"
                          style={{
                            fontSize: '10px', fontWeight: 700,
                            color: entry.result === 'EXECUTED' ? 'var(--its-signal-green)'
                              : entry.result === 'REJECTED' ? 'var(--its-signal-red)'
                                : 'var(--its-text-secondary)',
                          }}
                        >
                          {entry.result}
                        </span>
                      </td>
                      <td
                        className="mono"
                        style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}
                        title={entry.entry_hash ?? 'Unchained legacy entry'}
                      >
                        {entry.chained ? `${entry.entry_hash.slice(0, 10)}…` : 'UNCHAINED'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ACCESS MODEL ----------------------------------------------------- */}
      {tab === 'ACCESS' && (
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">Access Model</span>
            <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              YOUR ROLE: {scopes?.your_role}
            </span>
          </div>

          {!scopes ? (
            <SkeletonRows rows={4} label="Access model" />
          ) : (
            <>
              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', lineHeight: 1.7, marginBottom: '12px' }}>
                {scopes.note}
              </div>

              <div className="its-table-container">
                <table className="its-table">
                  <thead>
                    <tr>
                      <th>Role</th>
                      <th>Scopes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scopes.roles.map((role: any) => (
                      <tr key={role.role}>
                        <td style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
                          {role.role}
                          <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)', fontWeight: 400 }}>
                            {role.scope_count} granted
                          </div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                            {role.scopes.map((scope: string) => (
                              <span
                                key={scope}
                                className="mono"
                                style={{
                                  fontSize: '9px', padding: '1px 6px',
                                  borderRadius: 'var(--radius-full)',
                                  background: scope === 'signal:command'
                                    ? 'var(--its-signal-red-bg)' : 'var(--its-bg-subsurface)',
                                  border: `1px solid ${scope === 'signal:command'
                                    ? 'var(--its-signal-red-border)' : 'var(--its-border-subtle)'}`,
                                  color: scope === 'signal:command'
                                    ? 'var(--its-signal-red)' : 'var(--its-text-secondary)',
                                }}
                                title={
                                  scopes.scopes.find((s: any) => s.scope === scope)?.description
                                }
                              >
                                {scope}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {/* KEYS ------------------------------------------------------------- */}
      {tab === 'KEYS' && (
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">API Keys</span>
            <button onClick={() => setShowCreateKey(true)} className="its-btn its-btn-primary" style={{ padding: '3px 9px' }}>
              <Plus size={12} />
              <span>Issue key</span>
            </button>
          </div>

          {!keys ? (
            <SkeletonRows rows={3} label="API keys" />
          ) : keys.keys.length === 0 ? (
            <div className="mono" style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}>
              {keys.empty_reason}
            </div>
          ) : (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Prefix</th>
                    <th>Scopes</th>
                    <th>Status</th>
                    <th>Used</th>
                    <th>Expires</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {keys.keys.map((key: any) => (
                    <tr key={key.id}>
                      <td style={{ fontWeight: 600 }}>{key.name}</td>
                      <td className="mono" style={{ fontSize: '10px' }}>{key.key_prefix}…</td>
                      <td className="mono" style={{ fontSize: '10px' }}>{(key.scopes ?? []).join(', ')}</td>
                      <td>
                        <span
                          className="mono"
                          style={{
                            fontSize: '10px', fontWeight: 700,
                            color: key.status === 'ACTIVE' ? 'var(--its-signal-green)' : 'var(--its-text-muted)',
                          }}
                        >
                          {key.status}
                        </span>
                      </td>
                      <td className="mono">{key.use_count}</td>
                      <td className="mono" style={{ fontSize: '10px' }}>
                        {key.expires_at ? formatTimestamp(key.expires_at).slice(0, 10) : '—'}
                      </td>
                      <td>
                        {key.status === 'ACTIVE' && (
                          <button
                            onClick={() => revoke(key.id)}
                            className="its-btn its-btn-danger"
                            style={{ padding: '2px 7px' }}
                            aria-label={`Revoke ${key.name}`}
                          >
                            <Trash2 size={11} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {keys?.note && (
            <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '10px', lineHeight: 1.6 }}>
              {keys.note}
            </div>
          )}
        </div>
      )}

      {/* Create key drawer ------------------------------------------------ */}
      {showCreateKey && (
        <>
          <div className="drawer-backdrop" onClick={() => setShowCreateKey(false)} />
          <aside className="junction-drawer" role="dialog" aria-modal="true" aria-label="Issue API key">
            <div className="drawer-header">
              <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>ISSUE API KEY</span>
              <button
                onClick={() => setShowCreateKey(false)}
                aria-label="Close"
                style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--its-text-muted)' }}
              >
                <X size={17} />
              </button>
            </div>

            <div className="junction-drawer-body">
              <label style={fieldLabel} htmlFor="key-name">Key name</label>
              <input id="key-name" className="its-input" value={keyName} onChange={e => setKeyName(e.target.value)} placeholder="detector-ingest-agent" />

              <label style={fieldLabel}>Scopes</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                {(scopes?.scopes ?? []).map((scope: any) => {
                  const forbidden = ['signal:command', 'users:manage', 'apikeys:manage']
                    .includes(scope.scope);
                  return (
                    <label
                      key={scope.scope}
                      style={{
                        display: 'flex', alignItems: 'flex-start', gap: '7px',
                        fontSize: 'var(--text-2xs)',
                        opacity: forbidden ? 0.45 : 1,
                      }}
                      title={forbidden
                        ? 'A machine credential can never hold this scope.'
                        : scope.description}
                    >
                      <input
                        type="checkbox"
                        disabled={forbidden}
                        checked={keyScopes.includes(scope.scope)}
                        onChange={() =>
                          setKeyScopes(prev =>
                            prev.includes(scope.scope)
                              ? prev.filter(s => s !== scope.scope)
                              : [...prev, scope.scope])
                        }
                        style={{ accentColor: 'var(--its-text-accent)', marginTop: 2 }}
                      />
                      <span>
                        <span className="mono" style={{ fontWeight: 700 }}>{scope.scope}</span>
                        <div style={{ color: 'var(--its-text-muted)' }}>{scope.description}</div>
                      </span>
                    </label>
                  );
                })}
              </div>

              <label style={fieldLabel} htmlFor="key-exp">Expires in (days)</label>
              <input
                id="key-exp"
                type="number"
                className="its-input"
                value={expiresDays}
                onChange={e => setExpiresDays(Number(e.target.value))}
              />

              <div
                style={{
                  padding: '9px 11px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--its-bg-subsurface)', fontSize: 'var(--text-2xs)',
                  color: 'var(--its-text-secondary)', lineHeight: 1.6,
                }}
              >
                A key can never hold <span className="mono">signal:command</span>. Issuing a
                signal change requires a named accountable operator; a shared machine
                credential would record a meaningless actor in the audit ledger.
              </div>

              <button
                onClick={createKey}
                className="its-btn its-btn-primary"
                disabled={!keyName || keyScopes.length === 0}
                style={{ justifyContent: 'center' }}
              >
                <Key size={13} />
                <span>Issue key</span>
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
