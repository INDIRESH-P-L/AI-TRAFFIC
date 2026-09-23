import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Gauge, RefreshCw, Search, ShieldAlert } from 'lucide-react';
import { api } from '../api/client';
import { SkeletonRows } from '../components/Skeleton';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { TrustBadge, TrustPanel, trustScoreText } from '../components/TrustPanel';
import type { TrustResult } from '../components/TrustPanel';
import { VerificationPanel } from '../components/VerificationPanel';
import type { VerificationResult } from '../components/VerificationPanel';
import { formatTimestamp } from '../lib/quality';

/**
 * TRAFFICINTEL AI - Data Trust & Change Verification
 *
 * Two questions an operator cannot answer from the rest of the console:
 *
 *   "How much of what I'm looking at is real?"  -> trust score
 *   "Did the change I made actually do anything?" -> verification
 *
 * They sit together because they are the same discipline applied at two
 * points in time: before you act, and after.
 *
 * States:
 *   LOADING  skeleton rows, no numbers.
 *   EMPTY    no junctions configured -> TruthfulEmptyState pointing at setup.
 *            Junctions present but none rated -> the roll-up says so in words
 *            and the mean is withheld, never printed as 0.
 *   ERROR    the failure is named and a retry offered; no stale figure is
 *            left on screen pretending to be current.
 */

type Tab = 'TRUST' | 'VERIFICATION';

interface NetworkTrust {
  junction_count: number;
  rated_count: number;
  unrated_count: number;
  mean_score_of_rated: number | null;
  mean_basis: string;
  by_band: Record<string, number>;
  junctions: TrustResult[];
  ai_gated_junctions: any[];
  window_minutes: number;
}

const BAND_ORDER = ['UNTRUSTED', 'PARTIAL', 'TRUSTED', 'UNRATED'] as const;

export const DataTrust: React.FC = () => {
  const [tab, setTab] = useState<Tab>('TRUST');

  const [network, setNetwork] = useState<NetworkTrust | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [windowMinutes, setWindowMinutes] = useState(60);

  const loadNetwork = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getNetworkTrust(windowMinutes);
      setNetwork(data);
      setSelected((current) => current ?? data.junctions?.[0]?.intersection_id ?? null);
    } catch (e: any) {
      setNetwork(null);
      setError(e?.message || 'The trust roll-up could not be retrieved.');
    } finally {
      setLoading(false);
    }
  }, [windowMinutes]);

  useEffect(() => {
    void loadNetwork();
  }, [loadNetwork]);

  const visible = useMemo(() => {
    const list = network?.junctions || [];
    const needle = filter.trim().toLowerCase();
    const matched = needle
      ? list.filter((j) => (j.intersection_name || '').toLowerCase().includes(needle))
      : list;

    // Worst first: the junction you cannot trust is the one to look at.
    return [...matched].sort((a, b) => {
      const rank = (t: TrustResult) =>
        t.score === null ? 1000 : t.score;
      return rank(a) - rank(b);
    });
  }, [network, filter]);

  return (
    <div className="its-page">
      <div className="its-page-header">
        <div>
          <h1 className="its-page-title">
            <Gauge size={18} /> Data Trust &amp; Change Verification
          </h1>
          <p className="its-page-subtitle">
            How much of the console is backed by live sources, and whether the last change
            measurably did anything.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <select
            className="its-select"
            value={windowMinutes}
            onChange={(e) => setWindowMinutes(Number(e.target.value))}
            title="Assessment window"
          >
            <option value={15}>Last 15 min</option>
            <option value={60}>Last 60 min</option>
            <option value={240}>Last 4 h</option>
            <option value={1440}>Last 24 h</option>
          </select>
          <button className="its-btn its-btn-sm" onClick={() => void loadNetwork()}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="its-tabs" style={{ marginBottom: '14px' }}>
        <button
          className={`its-tab ${tab === 'TRUST' ? 'active' : ''}`}
          onClick={() => setTab('TRUST')}
        >
          <Gauge size={13} /> Trust Score
        </button>
        <button
          className={`its-tab ${tab === 'VERIFICATION' ? 'active' : ''}`}
          onClick={() => setTab('VERIFICATION')}
        >
          <Activity size={13} /> Change Verification
        </button>
      </div>

      {tab === 'TRUST' ? (
        <TrustTab
          network={network}
          loading={loading}
          error={error}
          onRetry={() => void loadNetwork()}
          visible={visible}
          filter={filter}
          setFilter={setFilter}
          selected={selected}
          setSelected={setSelected}
          windowMinutes={windowMinutes}
        />
      ) : (
        <VerificationTab junctions={network?.junctions || []} />
      )}
    </div>
  );
};

// ===========================================================================
// Trust tab
// ===========================================================================

const TrustTab: React.FC<{
  network: NetworkTrust | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  visible: TrustResult[];
  filter: string;
  setFilter: (v: string) => void;
  selected: string | null;
  setSelected: (v: string) => void;
  windowMinutes: number;
}> = ({ network, loading, error, onRetry, visible, filter, setFilter, selected, setSelected, windowMinutes }) => {
  if (loading) return <SkeletonRows rows={8} label="Assessing network data quality" />;

  if (error) {
    return (
      <div className="its-panel" style={{ padding: '18px' }}>
        <div style={{ color: 'var(--its-status-critical)', fontSize: '12px', fontWeight: 700 }}>
          TRUST ROLL-UP UNAVAILABLE
        </div>
        <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', marginTop: '6px' }}>
          {error} No figures are shown rather than showing figures that may be out of date.
        </div>
        <button className="its-btn its-btn-sm" style={{ marginTop: '12px' }} onClick={onRetry}>
          <RefreshCw size={13} /> Retry
        </button>
      </div>
    );
  }

  if (!network || network.junction_count === 0) {
    return (
      <TruthfulEmptyState
        title="NO JUNCTIONS CONFIGURED"
        description="Data quality is assessed per junction. Add a junction and connect a controller or detector before a trust score can be produced."
        actionText="Configure intersections"
        actionLink="/intersections"
      />
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 420px)', gap: '14px' }}>
      <div>
        {/* Network roll-up */}
        <div className="its-panel" style={{ marginBottom: '14px' }}>
          <div className="its-panel-header">
            <span>NETWORK ROLL-UP</span>
            <span style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              last {network.window_minutes} min
            </span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '22px', padding: '14px' }}>
            <div>
              <div className="its-metric-label">MEAN SCORE (RATED ONLY)</div>
              <div
                className="mono"
                style={{
                  fontSize: '26px',
                  fontWeight: 800,
                  color: network.mean_score_of_rated === null
                    ? 'var(--its-text-muted)'
                    : 'var(--its-text-primary)',
                }}
              >
                {network.mean_score_of_rated === null
                  ? '--'
                  : network.mean_score_of_rated.toFixed(1)}
              </div>
            </div>
            <div>
              <div className="its-metric-label">RATED</div>
              <div className="mono" style={{ fontSize: '26px', fontWeight: 800 }}>
                {network.rated_count}
                <span style={{ fontSize: '13px', color: 'var(--its-text-muted)' }}>
                  /{network.junction_count}
                </span>
              </div>
            </div>
            <div>
              <div className="its-metric-label">UNRATED</div>
              <div
                className="mono"
                style={{ fontSize: '26px', fontWeight: 800, color: 'var(--its-text-muted)' }}
              >
                {network.unrated_count}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              {BAND_ORDER.filter((band) => network.by_band?.[band]).map((band) => (
                <div key={band} style={{ textAlign: 'center' }}>
                  <TrustBadge band={band} score={band === 'UNRATED' ? null : 1} showLabel={false} />
                  <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', marginTop: '3px' }}>
                    {band} {network.by_band[band]}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div
            style={{
              padding: '9px 14px',
              borderTop: '1px solid var(--its-border-subtle)',
              fontSize: '10px',
              color: 'var(--its-text-muted)',
              lineHeight: 1.6,
            }}
          >
            {network.mean_basis}
          </div>
          {network.ai_gated_junctions?.length > 0 && (
            <div
              style={{
                display: 'flex',
                gap: '8px',
                padding: '9px 14px',
                borderTop: '1px solid var(--its-border-subtle)',
                background: 'var(--its-bg-elevated)',
                fontSize: '10px',
                lineHeight: 1.6,
              }}
            >
              <ShieldAlert size={13} style={{ color: 'var(--its-status-warning)', flexShrink: 0, marginTop: '1px' }} />
              <span>
                <strong style={{ color: 'var(--its-status-warning)' }}>
                  {network.ai_gated_junctions.length} junction(s) are withholding AI recommendations.
                </strong>{' '}
                The optimiser will not compute from measured demand at these junctions until their
                data quality recovers. Operator-entered volumes still work.
              </span>
            </div>
          )}
        </div>

        {/* Junction list, worst first */}
        <div className="its-panel">
          <div className="its-panel-header">
            <span>JUNCTIONS ({visible.length})</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <Search size={12} style={{ color: 'var(--its-text-muted)' }} />
              <input
                className="its-input its-input-sm"
                placeholder="Filter by name"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                style={{ width: '150px' }}
              />
            </div>
          </div>

          {visible.length === 0 ? (
            <div style={{ padding: '18px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
              No junction matches "{filter}".
            </div>
          ) : (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Junction</th>
                    <th style={{ width: '80px' }}>Score</th>
                    <th style={{ width: '110px' }}>Band</th>
                    <th>Limiting factor</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((junction) => (
                    <tr
                      key={junction.intersection_id}
                      onClick={() => setSelected(junction.intersection_id)}
                      style={{
                        cursor: 'pointer',
                        background:
                          selected === junction.intersection_id
                            ? 'var(--its-bg-elevated)'
                            : undefined,
                      }}
                    >
                      <td style={{ fontWeight: 600 }}>{junction.intersection_name}</td>
                      <td className="mono" style={{ fontWeight: 700 }}>
                        {trustScoreText(junction)}
                      </td>
                      <td>
                        <TrustBadge band={junction.band} score={junction.score} showLabel={false} />
                        <span style={{ marginLeft: '6px', fontSize: '10px' }}>{junction.band}</span>
                      </td>
                      <td style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                        {junction.weakest_component?.name.replace(/_/g, ' ') ||
                          (junction.band === 'UNRATED' ? 'not enough measured to rate' : '--')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div>
        {selected ? (
          <TrustPanel intersectionId={selected} windowMinutes={windowMinutes} />
        ) : (
          <div className="its-panel" style={{ padding: '16px', fontSize: '11px', color: 'var(--its-text-muted)' }}>
            Select a junction to see its component breakdown.
          </div>
        )}
      </div>
    </div>
  );
};

// ===========================================================================
// Verification tab
// ===========================================================================

const VerificationTab: React.FC<{ junctions: TrustResult[] }> = ({ junctions }) => {
  const [recent, setRecent] = useState<any[] | null>(null);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [recentError, setRecentError] = useState<string | null>(null);

  const [result, setResult] = useState<VerificationResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const [intersectionId, setIntersectionId] = useState('');
  const [changedAt, setChangedAt] = useState(() => {
    const now = new Date(Date.now() - 30 * 60_000);
    // datetime-local wants a local-time string with no zone suffix.
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
  });
  const [windowMinutes, setWindowMinutes] = useState(30);
  const [settleMinutes, setSettleMinutes] = useState(2);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingRecent(true);
      setRecentError(null);
      try {
        const data = await api.getRecentVerifications(undefined, 10);
        if (!cancelled) setRecent(data.verifications || data.items || []);
      } catch (e: any) {
        if (!cancelled) setRecentError(e?.message || 'Recent verifications could not be loaded.');
      } finally {
        if (!cancelled) setLoadingRecent(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const run = async () => {
    if (!intersectionId) return;
    setRunning(true);
    setRunError(null);
    setResult(null);
    try {
      // The local-time input is converted to a real instant before it goes to
      // the server; sending a bare local string would silently shift the
      // comparison windows by the operator's UTC offset.
      const iso = new Date(changedAt).toISOString();
      setResult(await api.verifyWindow(intersectionId, iso, windowMinutes, settleMinutes));
    } catch (e: any) {
      setRunError(e?.message || 'The comparison could not be run.');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 360px) minmax(0, 1fr)', gap: '14px' }}>
      <div>
        <div className="its-panel">
          <div className="its-panel-header">
            <span>COMPARE AROUND A CHANGE</span>
          </div>
          <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '11px' }}>
            <label style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              JUNCTION
              <select
                className="its-select"
                style={{ width: '100%', marginTop: '4px' }}
                value={intersectionId}
                onChange={(e) => setIntersectionId(e.target.value)}
              >
                <option value="">Select a junction...</option>
                {junctions.map((j) => (
                  <option key={j.intersection_id} value={j.intersection_id}>
                    {j.intersection_name}
                  </option>
                ))}
              </select>
            </label>

            <label style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
              CHANGE MADE AT (LOCAL TIME)
              <input
                type="datetime-local"
                className="its-input"
                style={{ width: '100%', marginTop: '4px' }}
                value={changedAt}
                onChange={(e) => setChangedAt(e.target.value)}
              />
            </label>

            <div style={{ display: 'flex', gap: '9px' }}>
              <label style={{ fontSize: '10px', color: 'var(--its-text-muted)', flex: 1 }}>
                WINDOW (MIN)
                <input
                  type="number"
                  className="its-input"
                  style={{ width: '100%', marginTop: '4px' }}
                  min={5}
                  max={480}
                  value={windowMinutes}
                  onChange={(e) => setWindowMinutes(Number(e.target.value))}
                />
              </label>
              <label style={{ fontSize: '10px', color: 'var(--its-text-muted)', flex: 1 }}>
                SETTLE (MIN)
                <input
                  type="number"
                  className="its-input"
                  style={{ width: '100%', marginTop: '4px' }}
                  min={0}
                  max={60}
                  value={settleMinutes}
                  onChange={(e) => setSettleMinutes(Number(e.target.value))}
                />
              </label>
            </div>

            <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', lineHeight: 1.6 }}>
              The settle period is excluded from both sides. A controller does not change
              behaviour the instant a command lands, and counting the transition as "after"
              would blur the very difference being measured.
            </div>

            <button
              className="its-btn its-btn-primary"
              disabled={!intersectionId || running}
              onClick={() => void run()}
            >
              <Activity size={13} /> {running ? 'Comparing...' : 'Compare before and after'}
            </button>

            {runError && (
              <div style={{ fontSize: '10px', color: 'var(--its-status-critical)' }}>{runError}</div>
            )}
          </div>
        </div>

        {/* Recently executed commands, each verifiable in one click */}
        <div className="its-panel" style={{ marginTop: '14px' }}>
          <div className="its-panel-header">
            <span>RECENT EXECUTED COMMANDS</span>
          </div>
          {loadingRecent ? (
            <SkeletonRows rows={3} label="Loading recent commands" />
          ) : recentError ? (
            <div style={{ padding: '14px', fontSize: '10px', color: 'var(--its-status-critical)' }}>
              {recentError}
            </div>
          ) : !recent?.length ? (
            <div style={{ padding: '14px', fontSize: '11px', color: 'var(--its-text-muted)', lineHeight: 1.6 }}>
              NO EXECUTED COMMANDS TO VERIFY. Verification compares telemetry either side of a
              command that actually reached a controller; commands rejected by the Safety Engine
              never did, so there is nothing to measure.
            </div>
          ) : (
            <div className="its-table-container">
              <table className="its-table">
                <thead>
                  <tr>
                    <th>Command</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((item: any) => (
                    <tr
                      key={item.command_id}
                      style={{ cursor: 'pointer' }}
                      onClick={() => {
                        setRunning(true);
                        setRunError(null);
                        api
                          .verifyCommand(item.command_id)
                          .then(setResult)
                          .catch((e: any) =>
                            setRunError(e?.message || 'Verification failed.'),
                          )
                          .finally(() => setRunning(false));
                      }}
                    >
                      <td>
                        <div style={{ fontSize: '11px', fontWeight: 600 }}>
                          {item.intersection_name || item.command_id?.slice(0, 8)}
                        </div>
                        <div style={{ fontSize: '9px', color: 'var(--its-text-muted)' }}>
                          {formatTimestamp(item.executed_at || item.requested_at)}
                        </div>
                      </td>
                      <td style={{ fontSize: '10px' }}>
                        {(item.overall_verdict || item.status || '').replace(/_/g, ' ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div>
        {running ? (
          <SkeletonRows rows={6} label="Comparing before and after" />
        ) : result ? (
          <VerificationPanel result={result} />
        ) : (
          <TruthfulEmptyState
            title="NO COMPARISON RUN YET"
            description="Pick a junction and the moment a change was made, or select an executed command. Verification compares recorded telemetry either side of that moment and reports a confidence interval - including 'no measurable change', which is a real answer rather than a failure."
          />
        )}
      </div>
    </div>
  );
};
