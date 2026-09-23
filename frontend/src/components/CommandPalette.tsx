import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity, AlertTriangle, Bot, CornerDownLeft, GitCommit, Loader2, Map,
  Moon, Play, Search, Settings, Sliders, Sun, X, Zap,
} from 'lucide-react';
import { api } from '../api/client';
import { useConsole } from '../context/ConsoleContext';

/**
 * TRAFFICINTEL AI - Command palette
 *
 * Three kinds of result, in one list:
 *   NAVIGATE  jump to a route, junction, controller or incident
 *   ACTION    run something (acknowledge an incident, toggle a preference)
 *   ASK       put the query to the grounded Copilot
 *
 * Actions that change traffic control are deliberately NOT executed from here.
 * "Open junction J-04 timing plan" navigates to the guided command workflow; it
 * does not issue a hold. A palette is a fast path for an operator's intent, and
 * a fast path to a signal change is exactly the affordance this platform should
 * not have.
 */

type ItemKind = 'NAVIGATE' | 'ACTION' | 'ASK';

interface PaletteItem {
  id: string;
  title: string;
  subtitle: string;
  kind: ItemKind;
  icon: React.ReactNode;
  keywords?: string;
  run: () => void | Promise<void>;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenCommandWorkflow?: (controllerId: string | null) => void;
  onOpenWizard?: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onOpenCommandWorkflow,
  onOpenWizard,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [entities, setEntities] = useState<PaletteItem[]>([]);
  const [loadingEntities, setLoadingEntities] = useState(false);
  const [copilotAnswer, setCopilotAnswer] = useState<any>(null);
  const [askingCopilot, setAskingCopilot] = useState(false);

  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const { theme, setTheme, density, setDensity, wallboard, setWallboard, notify } = useConsole();

  // --- Static navigation + preference actions ---------------------------
  const staticItems = useMemo<PaletteItem[]>(() => {
    const go = (path: string) => () => {
      navigate(path);
      onClose();
    };

    return [
      { id: 'nav-dash', title: 'Dashboard', subtitle: 'Network overview & operations map', kind: 'NAVIGATE', icon: <Activity size={15} />, run: go('/dashboard') },
      { id: 'nav-map', title: 'Live GIS Operations Map', subtitle: 'Layered spatial monitoring', kind: 'NAVIGATE', icon: <Map size={15} />, run: go('/live-map') },
      { id: 'nav-junctions', title: 'Intersections & Signals', subtitle: 'Junction topologies & NEMA TS2 timing', kind: 'NAVIGATE', icon: <Sliders size={15} />, run: go('/intersections') },
      { id: 'nav-incidents', title: 'Incident Console', subtitle: 'Triage, assignment & clearance', kind: 'NAVIGATE', icon: <AlertTriangle size={15} />, run: go('/incidents') },
      { id: 'nav-copilot', title: 'AI Operations Copilot', subtitle: 'Grounded query assistant', kind: 'NAVIGATE', icon: <Bot size={15} />, run: go('/ai-copilot') },
      { id: 'nav-settings', title: 'Settings & Health', subtitle: 'Hardware wizards & system status', kind: 'NAVIGATE', icon: <Settings size={15} />, run: go('/settings') },

      {
        id: 'act-wizard',
        title: 'Connect infrastructure',
        subtitle: 'Open the guided connection wizard',
        kind: 'ACTION',
        icon: <Zap size={15} />,
        keywords: 'onboard add controller camera sensor setup',
        run: () => {
          onOpenWizard?.();
          onClose();
        },
      },
      {
        id: 'act-command',
        title: 'Issue a signal command',
        subtitle: 'Opens the guided workflow — never sends directly',
        kind: 'ACTION',
        icon: <Sliders size={15} />,
        keywords: 'phase hold timing plan control',
        run: () => {
          onOpenCommandWorkflow?.(null);
          onClose();
        },
      },
      {
        id: 'act-theme',
        title: `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`,
        subtitle: `Currently: ${theme}`,
        kind: 'ACTION',
        icon: theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />,
        keywords: 'dark light appearance contrast night shift',
        run: () => {
          setTheme(theme === 'dark' ? 'light' : 'dark');
          onClose();
        },
      },
      {
        id: 'act-density',
        title: `Switch to ${density === 'compact' ? 'comfortable' : 'compact'} density`,
        subtitle: `Currently: ${density}`,
        kind: 'ACTION',
        icon: <Activity size={15} />,
        keywords: 'compact comfortable rows spacing',
        run: () => {
          setDensity(density === 'compact' ? 'comfortable' : 'compact');
          onClose();
        },
      },
      {
        id: 'act-wallboard',
        title: `${wallboard ? 'Exit' : 'Enter'} wallboard mode`,
        subtitle: 'Large-format display for control-room screens',
        kind: 'ACTION',
        icon: <Map size={15} />,
        keywords: 'wallboard big screen tv control room',
        run: () => {
          setWallboard(!wallboard);
          onClose();
        },
      },
    ];
  }, [navigate, onClose, theme, setTheme, density, setDensity, wallboard, setWallboard, onOpenWizard, onOpenCommandWorkflow]);

  // --- Live entities ----------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;

    setQuery('');
    setSelectedIndex(0);
    setCopilotAnswer(null);
    setTimeout(() => inputRef.current?.focus(), 40);

    setLoadingEntities(true);
    Promise.all([
      api.getIntersections().catch(() => []),
      api.getControllers().catch(() => []),
      api.getIncidents().catch(() => []),
    ])
      .then(([intersections, controllers, incidents]) => {
        const items: PaletteItem[] = [];

        intersections.forEach((item: any) => {
          items.push({
            id: `int-${item.id}`,
            title: item.name,
            subtitle: `Junction · ${item.code} · controller ${item.controller_status ?? 'NOT CONFIGURED'}`,
            kind: 'NAVIGATE',
            icon: <GitCommit size={15} color="var(--its-text-accent)" />,
            keywords: `${item.code} junction intersection`,
            run: () => {
              navigate(`/intersections/${item.id}`);
              onClose();
            },
          });
        });

        controllers.forEach((ctrl: any) => {
          items.push({
            id: `ctrl-${ctrl.id}`,
            title: `${ctrl.name} timing plan`,
            subtitle: `Controller · ${ctrl.protocol} · ${ctrl.connection_status} · ${ctrl.ip_address}`,
            kind: 'ACTION',
            icon: <Sliders size={15} color="var(--its-signal-green)" />,
            keywords: `${ctrl.ip_address} controller phase hold command`,
            run: () => {
              onOpenCommandWorkflow?.(ctrl.id);
              onClose();
            },
          });
        });

        incidents.forEach((inc: any) => {
          const canAcknowledge = ['DETECTED', 'SUSPECTED'].includes(inc.status);
          items.push({
            id: `inc-${inc.id}`,
            title: canAcknowledge ? `Acknowledge: ${inc.title}` : inc.title,
            subtitle: `Incident · ${inc.severity} · ${inc.status}`,
            kind: canAcknowledge ? 'ACTION' : 'NAVIGATE',
            icon: <AlertTriangle size={15} color="var(--its-signal-red)" />,
            keywords: `incident ${inc.type} ${inc.severity} acknowledge verify`,
            run: async () => {
              if (canAcknowledge) {
                try {
                  await api.updateIncidentStatus(inc.id, {
                    status: 'VERIFIED',
                    operator_notes: 'Acknowledged from command palette.',
                  });
                  notify({
                    severity: 'INFO',
                    title: `Incident acknowledged: ${inc.title}`,
                    detail: 'Status moved to VERIFIED',
                    origin: 'operator.action',
                    link: '/incidents',
                  });
                } catch (err: any) {
                  notify({
                    severity: 'WARNING',
                    title: 'Could not acknowledge incident',
                    detail: err.message,
                    origin: 'operator.action',
                  });
                }
              }
              navigate('/incidents');
              onClose();
            },
          });
        });

        setEntities(items);
      })
      .finally(() => setLoadingEntities(false));
  }, [isOpen, navigate, onClose, onOpenCommandWorkflow, notify]);

  // --- Filtering --------------------------------------------------------
  const matches = useMemo(() => {
    const all = [...staticItems, ...entities];
    const q = query.trim().toLowerCase();
    if (!q) return staticItems;

    return all.filter(item =>
      item.title.toLowerCase().includes(q) ||
      item.subtitle.toLowerCase().includes(q) ||
      (item.keywords ?? '').toLowerCase().includes(q),
    );
  }, [staticItems, entities, query]);

  const askCopilot = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setAskingCopilot(true);
    setCopilotAnswer(null);
    try {
      const response = await api.queryCopilot(q);
      setCopilotAnswer(response);
    } catch (err: any) {
      setCopilotAnswer({ answer: `Copilot request failed: ${err.message}`, citations: [] });
    } finally {
      setAskingCopilot(false);
    }
  }, [query]);

  // Natural-language ask is always the last entry when there is a query.
  const items = useMemo<PaletteItem[]>(() => {
    if (!query.trim()) return matches;
    return [
      ...matches,
      {
        id: 'ask-copilot',
        title: `Ask the Copilot: "${query.trim()}"`,
        subtitle: 'Answers only from stored records and indexed standards',
        kind: 'ASK',
        icon: <Bot size={15} color="var(--its-text-indigo)" />,
        run: askCopilot,
      },
    ];
  }, [matches, query, askCopilot]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex(prev => (prev + 1) % (items.length || 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(prev => (prev - 1 + items.length) % (items.length || 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        void items[selectedIndex]?.run();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, items, selectedIndex, onClose]);

  if (!isOpen) return null;

  const KIND_BADGE: Record<ItemKind, { label: string; color: string }> = {
    NAVIGATE: { label: 'GO', color: 'var(--its-text-accent)' },
    ACTION: { label: 'RUN', color: 'var(--its-signal-green)' },
    ASK: { label: 'ASK', color: 'var(--its-text-indigo)' },
  };

  return (
    <div className="command-palette-backdrop" onClick={onClose}>
      <div
        className="command-palette-modal"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="palette-input-wrap">
          <Search size={17} color="var(--its-text-accent)" />
          <input
            ref={inputRef}
            type="text"
            className="palette-input"
            placeholder="Jump to a junction, run an action, or ask a question…"
            aria-label="Search junctions, actions and questions"
            value={query}
            onChange={e => {
              setQuery(e.target.value);
              setSelectedIndex(0);
              setCopilotAnswer(null);
            }}
          />
          {loadingEntities && <Loader2 size={14} className="pulse-indicator" color="var(--its-text-muted)" />}
          <button
            onClick={onClose}
            aria-label="Close command palette"
            style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer', padding: '4px' }}
          >
            <X size={15} />
          </button>
        </div>

        <div className="palette-results">
          {items.length === 0 ? (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--its-text-muted)', fontSize: 'var(--text-xs)' }}>
              Nothing matches "{query}". Press Enter to ask the Copilot instead.
            </div>
          ) : (
            items.map((item, idx) => {
              const badge = KIND_BADGE[item.kind];
              return (
                <div
                  key={item.id}
                  className={`palette-item ${idx === selectedIndex ? 'selected' : ''}`}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  onClick={() => void item.run()}
                  role="button"
                  tabIndex={-1}
                >
                  <div className="palette-item-left">
                    {item.icon}
                    <div>
                      <div className="palette-item-title">{item.title}</div>
                      <div className="palette-item-subtitle">{item.subtitle}</div>
                    </div>
                  </div>
                  <div className="palette-item-badge" style={{ color: badge.color }}>
                    {badge.label}
                  </div>
                </div>
              );
            })
          )}

          {/* Copilot answer, grounded and cited */}
          {(askingCopilot || copilotAnswer) && (
            <div
              style={{
                margin: '8px', padding: '12px',
                border: '1px solid var(--its-border-accent)',
                borderRadius: 'var(--radius-md)', background: 'var(--its-fresh-bg)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '7px' }}>
                <Bot size={14} color="var(--its-text-indigo)" />
                <span style={{ fontSize: 'var(--text-2xs)', fontWeight: 700 }}>COPILOT</span>
                {copilotAnswer?.telemetry_state && (
                  <span className="mono" style={{ fontSize: '9px', color: 'var(--its-text-muted)' }}>
                    {copilotAnswer.telemetry_state}
                  </span>
                )}
              </div>

              {askingCopilot ? (
                <div className="skeleton" style={{ height: 40 }} />
              ) : (
                <>
                  <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-primary)', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                    {copilotAnswer.answer}
                  </div>

                  {copilotAnswer.citations?.length > 0 && (
                    <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--its-border-subtle)' }}>
                      <div style={{ fontSize: '9px', fontWeight: 700, color: 'var(--its-text-muted)', marginBottom: '4px' }}>
                        CITATIONS
                      </div>
                      {copilotAnswer.citations.map((citation: any, i: number) => (
                        <div key={i} className="mono" style={{ fontSize: '9px', color: 'var(--its-text-secondary)' }}>
                          {citation.title} ({citation.category})
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        <div className="palette-footer">
          <span>Navigate <kbd className="search-shortcut-kbd">↑</kbd> <kbd className="search-shortcut-kbd">↓</kbd></span>
          <span>Select <kbd className="search-shortcut-kbd"><CornerDownLeft size={10} style={{ display: 'inline' }} /></kbd></span>
          <span>Close <kbd className="search-shortcut-kbd">ESC</kbd></span>
          <span style={{ marginLeft: 'auto', color: 'var(--its-text-muted)' }}>
            <Play size={9} style={{ display: 'inline', marginRight: 3 }} />
            Signal changes always open the guided workflow
          </span>
        </div>
      </div>
    </div>
  );
};
