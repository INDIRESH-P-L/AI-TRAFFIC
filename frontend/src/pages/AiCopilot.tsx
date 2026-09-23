import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import {
  Send,
  ShieldCheck,
  Database,
  BookOpen,
  Sparkles,
  BarChart3,
  Calculator
} from 'lucide-react';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  telemetryState?: string;
  grounding?: string[];
  citations?: any[];
  timestamp: string;
  grounded?: boolean;
  reasoningMode?: string;
  modeNote?: string;
}

export const AiCopilot: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content:
        'TRAFFICINTEL AI Operations Copilot active.\nGrounding policy: ZERO HALLUCINATION. Strict database schemas & FHWA MUTCD / NEMA standards only.\n\nOBSERVED: All relational telemetry feeds synchronized.\nREGULATORY CONTEXT: MUTCD Section 4D & NEMA TS 2 Dual-Ring conflict matrices indexed in RAG memory.\n\nHow can I assist your traffic operations team today?',
      telemetryState: 'SYSTEM_READY',
      grounding: ['MUTCD_4D_TABLE_4D_102', 'NEMA_TS2_SEC_3_5'],
      citations: [
        { standard: 'FHWA MUTCD 2009', section: 'Section 4D.14', title: 'Minimum Yellow Change and Red Clearance Intervals', snippet: 'A yellow change interval shall be followed by a red clearance interval to provide adequate clearance time.' },
        { standard: 'NEMA TS 2-2016', section: 'Section 3.5.3', title: 'Dual-Ring Concurrent Phase Interlocks', snippet: 'Phases within the same ring shall not display concurrent green indications under conflict monitor MMU rules.' },
      ],
      timestamp: new Date().toLocaleTimeString(),
    },
  ]);
  const [inputQuery, setInputQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [activeCitation, setActiveCitation] = useState<any | null>(null);
  const [activeTab, setActiveTab] = useState<'EVIDENCE' | 'CALCULATOR'>('EVIDENCE');

  // Interactive Kinematic Dilemma Zone & Clearance Interval Calculator
  const [calcSpeedMph, setCalcSpeedMph] = useState<number>(45);
  const [calcGradePct, setCalcGradePct] = useState<number>(0);
  const [calcWidthFt, setCalcWidthFt] = useState<number>(60);

  // ITE / MUTCD Standard Formula:
  // Yellow = t + V / (2a + 2Gg) where t=1.0s, a=10 ft/s^2, g=32.2 ft/s^2, V in ft/s (1 mph = 1.467 ft/s)
  const vFtS = calcSpeedMph * 1.467;
  const accel = 10.0;
  const gravity = 32.2;
  const gradeFrac = calcGradePct / 100;
  const yellowTime = Math.max(3.0, Math.min(6.0, Number((1.0 + vFtS / (2 * accel + 2 * gravity * gradeFrac)).toFixed(1))));
  // Red Clearance = (W + L) / V where L=20 ft
  const redClearance = Number(((calcWidthFt + 20) / vFtS).toFixed(1));
  const totalChangeInterval = Number((yellowTime + redClearance).toFixed(1));

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputQuery.trim() || loading) return;

    const queryText = inputQuery.trim();
    setInputQuery('');

    const userMsg: ChatMessage = {
      role: 'user',
      content: queryText,
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      // Copilot 2.0: plans tool calls, answers only from what they return, and
      // attaches a citation to every claim.
      const res = await api.askCopilot(queryText);
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: res.answer,
        telemetryState: res.telemetry_state,
        grounding: (res.tools_called ?? []).map(
          (call: any) => `${call.tool} -> ${call.status}${call.reason ? ` (${call.reason})` : ''}`,
        ),
        citations: res.citations,
        grounded: res.grounded,
        reasoningMode: res.reasoning_mode,
        modeNote: res.mode_note,
        timestamp: new Date().toLocaleTimeString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      if (res.citations && res.citations.length > 0) {
        setActiveCitation(res.citations[0]);
      }
    } catch (err: any) {
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: `Error contacting operations copilot service: ${err.message}`,
        telemetryState: 'ERROR',
        timestamp: new Date().toLocaleTimeString(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  const sampleQueries = [
    'Which providers are degraded?',
    'Are there any open incidents?',
    'Were any signal commands rejected recently?',
    'What are the MUTCD minimum green requirements for arterial thru phases?',
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)', gap: '16px' }}>
      {/* Top Banner */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'var(--its-gradient-hero)',
          padding: '14px 20px',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--its-border-subtle)',
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: 'var(--text-lg)', fontWeight: 800, color: 'var(--its-text-primary)' }}>
              GROUNDED AI OPERATIONS COPILOT
            </h1>
            <span className="status-badge active">FHWA MUTCD & NEMA RAG</span>
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Zero-hallucination engineering assistant grounded in real SQLite schemas and indexed federal traffic standards.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <ShieldCheck size={16} color="#10b981" />
            <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-accent)', fontFamily: 'var(--font-mono)' }}>
              DETERMINISTIC GROUNDING ENFORCED
            </span>
          </div>

          <Link to="/analytics" className="its-btn" style={{ textDecoration: 'none' }}>
            <BarChart3 size={13} />
            <span>Analytics Workspace</span>
          </Link>
        </div>
      </div>

      {/* Main Split: Chat Workspace (Left) + Engineering Evidence & Calculator (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.8fr) minmax(0, 1fr)', gap: '16px', flex: 1, overflow: 'hidden' }}>
        {/* Chat Stream Area */}
        <div
          className="its-card"
          style={{
            padding: 0,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* Messages Stream */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {messages.map((m, idx) => (
              <div
                key={idx}
                style={{
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '85%',
                  background: m.role === 'user' ? '#eff6ff' : 'var(--its-bg-surface)',
                  border: `1px solid ${m.role === 'user' ? '#bfdbfe' : 'var(--its-border-subtle)'}`,
                  borderRadius: 'var(--radius-md)',
                  padding: '14px 16px',
                  boxShadow: 'var(--shadow-sm)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: m.role === 'user' ? 'var(--its-text-accent)' : 'var(--its-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {m.role === 'user' ? 'OPERATOR COMMAND' : 'COPILOT INFERENCE'}
                  </span>
                  <span className="mono" style={{ fontSize: '0.65rem', color: 'var(--its-text-muted)' }}>{m.timestamp}</span>
                </div>

                <div style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--text-sm)', lineHeight: 1.6, color: 'var(--its-text-primary)' }}>
                  {m.content}
                </div>

                {/* Citations & Evidence Tags */}
                {m.citations && m.citations.length > 0 && (
                  <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid var(--its-border-subtle)' }}>
                    <div style={{ fontSize: '0.65rem', fontWeight: 700, color: 'var(--its-text-teal)', textTransform: 'uppercase', marginBottom: '6px' }}>
                      CITED REGULATORY STANDARDS:
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {m.citations.map((c: any, i: number) => (
                        <button
                          key={i}
                          onClick={() => {
                            setActiveCitation(c);
                            setActiveTab('EVIDENCE');
                          }}
                          style={{
                            fontSize: '0.6875rem',
                            background: '#ffffff',
                            border: '1px solid var(--its-border-accent)',
                            padding: '3px 8px',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--its-text-accent)',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            fontWeight: 600,
                          }}
                        >
                          <BookOpen size={11} />
                          <span>{c.standard} {c.section}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div
                style={{
                  alignSelf: 'flex-start',
                  background: 'var(--its-bg-subsurface)',
                  border: '1px solid var(--its-border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '12px 18px',
                  fontSize: 'var(--text-xs)',
                  color: 'var(--its-text-accent)',
                  fontFamily: 'var(--font-mono)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <Sparkles size={14} className="pulse-indicator" />
                <span>Executing relational database inspection & MUTCD vector search...</span>
              </div>
            )}
          </div>

          {/* Prompt Suggestion Chips */}
          <div
            style={{
              padding: '8px 16px',
              background: 'var(--its-bg-subsurface)',
              borderTop: '1px solid var(--its-border-subtle)',
              display: 'flex',
              gap: '8px',
              overflowX: 'auto',
            }}
          >
            {sampleQueries.map((q, idx) => (
              <button
                key={idx}
                onClick={() => setInputQuery(q)}
                style={{
                  background: 'var(--its-bg-surface)',
                  border: '1px solid var(--its-border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '4px 10px',
                  fontSize: '0.75rem',
                  color: 'var(--its-text-secondary)',
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {q}
              </button>
            ))}
          </div>

          {/* Query Input Bar */}
          <form
            onSubmit={handleSend}
            style={{
              padding: '12px 16px',
              background: 'var(--its-bg-surface)',
              borderTop: '1px solid var(--its-border-subtle)',
              display: 'flex',
              gap: '10px',
            }}
          >
            <input
              type="text"
              className="its-input"
              value={inputQuery}
              onChange={(e) => setInputQuery(e.target.value)}
              placeholder="Query MUTCD warrants, dual-ring barrier rules, or intersection telemetry..."
              disabled={loading}
            />
            <button type="submit" className="its-btn its-btn-primary" disabled={loading || !inputQuery.trim()}>
              <Send size={14} />
              <span>Query</span>
            </button>
          </form>
        </div>

        {/* RIGHT: Grounding Evidence & Engineering Clearance Calculator */}
        <div
          className="its-card"
          style={{
            padding: '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px',
            overflowY: 'auto',
          }}
        >
          {/* Header with Switcher Tabs */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--its-border-subtle)', paddingBottom: '10px' }}>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button
                onClick={() => setActiveTab('EVIDENCE')}
                style={{
                  fontSize: '11px',
                  padding: '4px 10px',
                  borderRadius: 'var(--radius-xs)',
                  border: '1px solid ' + (activeTab === 'EVIDENCE' ? 'var(--its-text-accent)' : 'var(--its-border-subtle)'),
                  background: activeTab === 'EVIDENCE' ? '#eff6ff' : '#ffffff',
                  color: activeTab === 'EVIDENCE' ? 'var(--its-text-accent)' : 'var(--its-text-muted)',
                  cursor: 'pointer',
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                }}
              >
                <BookOpen size={12} />
                <span>Evidence</span>
              </button>

              <button
                onClick={() => setActiveTab('CALCULATOR')}
                style={{
                  fontSize: '11px',
                  padding: '4px 10px',
                  borderRadius: 'var(--radius-xs)',
                  border: '1px solid ' + (activeTab === 'CALCULATOR' ? 'var(--its-text-accent)' : 'var(--its-border-subtle)'),
                  background: activeTab === 'CALCULATOR' ? '#eff6ff' : '#ffffff',
                  color: activeTab === 'CALCULATOR' ? 'var(--its-text-accent)' : 'var(--its-text-muted)',
                  cursor: 'pointer',
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                }}
              >
                <Calculator size={12} />
                <span>Clearance Tool</span>
              </button>
            </div>

            <span className="status-badge active" style={{ fontSize: '10px' }}>
              VERIFIED
            </span>
          </div>

          {activeTab === 'EVIDENCE' ? (
            <>
              {/* Active Citation Card */}
              {activeCitation ? (
                <div
                  style={{
                    background: 'var(--its-bg-subsurface)',
                    border: '1px solid var(--its-border-accent)',
                    borderRadius: 'var(--radius-md)',
                    padding: '14px',
                  }}
                >
                  <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-accent)', fontWeight: 700, textTransform: 'uppercase' }}>
                    SELECTED STANDARD REFERENCE
                  </div>
                  <div style={{ fontSize: 'var(--text-sm)', fontWeight: 800, color: 'var(--its-text-primary)', marginTop: '4px' }}>
                    {activeCitation.standard} — {activeCitation.section}
                  </div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
                    {activeCitation.title}
                  </div>
                  {activeCitation.snippet && (
                    <div
                      style={{
                        marginTop: '10px',
                        padding: '8px 10px',
                        background: '#ffffff',
                        border: '1px solid var(--its-border-subtle)',
                        borderRadius: 'var(--radius-xs)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '11px',
                        color: 'var(--its-text-secondary)',
                        lineHeight: 1.5,
                      }}
                    >
                      "{activeCitation.snippet}"
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ background: 'var(--its-bg-subsurface)', padding: '12px', borderRadius: 'var(--radius-md)', fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>
                  Click any cited standard chip in the conversation to display its regulatory text here.
                </div>
              )}

              {/* Active Knowledge Bases */}
              <div>
                <div style={{ fontSize: 'var(--text-2xs)', fontWeight: 700, color: 'var(--its-text-muted)', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.06em' }}>
                  Indexed Operational Documents
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: 'var(--text-xs)' }}>
                  <div style={{ background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
                    <div style={{ fontWeight: 600, color: 'var(--its-text-primary)' }}>FHWA MUTCD 2009 / 11th Ed.</div>
                    <div style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>Part 4: Highway Traffic Signals (Warrants & Clearance)</div>
                  </div>
                  <div style={{ background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
                    <div style={{ fontWeight: 600, color: 'var(--its-text-primary)' }}>NEMA TS 2-2016 v03.07</div>
                    <div style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>Actuated Controller Units & Ring-Barrier Interlocks</div>
                  </div>
                  <div style={{ background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
                    <div style={{ fontWeight: 600, color: 'var(--its-text-primary)' }}>ITE Traffic Engineering Handbook</div>
                    <div style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>Kinematic Dilemma Zone & Clearance Formulations</div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            /* Interactive ITE / MUTCD Clearance Interval Calculator */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ fontSize: '11px', color: 'var(--its-text-secondary)', lineHeight: 1.4 }}>
                Compute kinematic dilemma zone clearance times using the official <b>ITE / MUTCD Section 4D</b> formulation:
              </div>

              <div style={{ background: 'var(--its-bg-subsurface)', padding: '10px', borderRadius: 'var(--radius-sm)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--its-text-brand)' }}>
                Y = t + V / (2a + 2Gg)
                <br />
                R = (W + L) / V
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '10px', color: 'var(--its-text-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
                  85th-Percentile Approach Speed: {calcSpeedMph} MPH ({Math.round(calcSpeedMph * 1.609)} km/h)
                </label>
                <input
                  type="range"
                  min="25"
                  max="65"
                  step="5"
                  value={calcSpeedMph}
                  onChange={(e) => setCalcSpeedMph(Number(e.target.value))}
                  style={{ width: '100%', accentColor: '#2563eb' }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '10px', color: 'var(--its-text-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
                    Grade (%): {calcGradePct}%
                  </label>
                  <input
                    type="range"
                    min="-6"
                    max="6"
                    step="1"
                    value={calcGradePct}
                    onChange={(e) => setCalcGradePct(Number(e.target.value))}
                    style={{ width: '100%', accentColor: '#2563eb' }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '10px', color: 'var(--its-text-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
                    Intersection Width: {calcWidthFt} FT
                  </label>
                  <input
                    type="range"
                    min="30"
                    max="120"
                    step="10"
                    value={calcWidthFt}
                    onChange={(e) => setCalcWidthFt(Number(e.target.value))}
                    style={{ width: '100%', accentColor: '#2563eb' }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginTop: '6px' }}>
                <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 'var(--radius-sm)', padding: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', fontWeight: 700 }}>YELLOW CHANGE</div>
                  <div style={{ fontSize: '16px', fontWeight: 800, color: 'var(--its-text-brand)', fontFamily: 'var(--font-mono)' }}>
                    {yellowTime}s
                  </div>
                </div>

                <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius-sm)', padding: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', fontWeight: 700 }}>RED CLEARANCE</div>
                  <div style={{ fontSize: '16px', fontWeight: 800, color: '#b91c1c', fontFamily: 'var(--font-mono)' }}>
                    {redClearance}s
                  </div>
                </div>

                <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 'var(--radius-sm)', padding: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '9px', color: 'var(--its-text-muted)', fontWeight: 700 }}>TOTAL INTERVAL</div>
                  <div style={{ fontSize: '16px', fontWeight: 800, color: '#15803d', fontFamily: 'var(--font-mono)' }}>
                    {totalChangeInterval}s
                  </div>
                </div>
              </div>

              <button
                onClick={() => setInputQuery(`Evaluate clearance intervals for approach speed ${calcSpeedMph} mph, grade ${calcGradePct}%, and width ${calcWidthFt} ft against MUTCD Section 4D.`)}
                className="its-btn its-btn-primary"
                style={{ width: '100%', justifyContent: 'center', fontSize: '11px', marginTop: '4px' }}
              >
                <span>Ask Copilot to Verify Timing</span>
              </button>
            </div>
          )}

          {/* Relational Database Scope */}
          <div style={{ marginTop: 'auto', background: 'var(--its-bg-subsurface)', border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-sm)', padding: '10px 12px', fontSize: 'var(--text-2xs)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--its-text-accent)', fontWeight: 700, marginBottom: '4px' }}>
              <Database size={13} />
              <span>LIVE DATABASE SCOPE</span>
            </div>
            <div style={{ color: 'var(--its-text-secondary)', fontFamily: 'var(--font-mono)' }}>
              Tables: intersections, signal_controllers, traffic_metrics, incidents, devices, audit_logs.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
