import React, { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  Map,
  Sliders,
  AlertTriangle,
  Bot,
  Settings,
  LogOut,
  Wifi,
  WifiOff,
  ChevronLeft,
  ChevronRight,
  Search,
  Bell,
  Clock,
  ShieldCheck,
  Layers,
  Keyboard,
  Moon,
  Sun,
  Rows3,
  MonitorPlay,
  Calculator,
  BellRing,
  HeartPulse,
  ScrollText,
  Gauge,
  Waves,
  ClipboardList,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useConsole } from '../context/ConsoleContext';
import { CommandPalette } from './CommandPalette';
import { NotificationCenter, ToastStack } from './NotificationCenter';
import { ShortcutsSheet } from './ShortcutsSheet';
import { SignalCommandWorkflow } from './SignalCommandWorkflow';
import { OnboardingWizard } from './OnboardingWizard';
import { api } from '../api/client';
import { formatAge } from '../lib/quality';
import { useTickingAge } from '../hooks/useTickingAge';

export const Layout: React.FC = () => {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const {
    connection, lastEventAt, unreadCount, notify, droppedEvents,
    theme, setTheme, density, setDensity, wallboard, setWallboard,
  } = useConsole();

  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('toc_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });
  const [isPaletteOpen, setIsPaletteOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [commandControllerId, setCommandControllerId] = useState<string | null | undefined>(undefined);
  const [controllers, setControllers] = useState<any[]>([]);
  const [openIncidentCount, setOpenIncidentCount] = useState(0);
  const [utcTime, setUtcTime] = useState('');
  const [systemStatus, setSystemStatus] = useState<any>(null);
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);

  const wsConnected = connection === 'CONNECTED';
  const lastEventAge = useTickingAge(lastEventAt);

  // Update live UTC time clock every second
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setUtcTime(now.toUTCString().replace('GMT', 'UTC'));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  // Check alert count on initial load and periodically
  useEffect(() => {
    const fetchStatus = () => {
      api.getDashboardSummary()
        .then(summary => {
          setOpenIncidentCount(
            (summary.alerts?.unacknowledged_count || 0) + (summary.incidents?.active_count || 0),
          );
          setApiReachable(true);
        })
        .catch(() => setApiReachable(false));

      api.getSystemStatus()
        .then(status => setSystemStatus(status))
        .catch(() => setSystemStatus(null));

      api.getControllers()
        .then(list => setControllers(list))
        .catch(() => setControllers([]));
    };
    fetchStatus();
    // Backstop poll only. Live updates arrive over the event stream; this
    // catches state that changed while the socket was down.
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  // The real-time stream lives in ConsoleContext so every page shares one
  // socket. Layout only renders its health.

  // Toggle sidebar collapse
  const toggleSidebar = () => {
    setIsCollapsed(prev => {
      const next = !prev;
      localStorage.setItem('toc_sidebar_collapsed', String(next));
      return next;
    });
  };

  // Keyboard shortcuts. Every binding here is listed in the "?" sheet.
  const pendingChord = useRef<string | null>(null);

  useEffect(() => {
    const isTyping = () => {
      const el = document.activeElement;
      if (!el) return false;
      const tag = el.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
        (el as HTMLElement).isContentEditable;
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd+K works even inside a field; everything else defers to typing.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsPaletteOpen(prev => !prev);
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping()) return;

      // Two-key 'g' chords for navigation.
      if (pendingChord.current === 'g') {
        pendingChord.current = null;
        const destinations: Record<string, string> = {
          d: '/dashboard', m: '/live-map', i: '/incidents', s: '/settings',
        };
        const path = destinations[e.key.toLowerCase()];
        if (path) {
          e.preventDefault();
          navigate(path);
        }
        return;
      }

      switch (e.key) {
        case 'g':
          pendingChord.current = 'g';
          // A chord that is never completed must not swallow the next keypress.
          setTimeout(() => { pendingChord.current = null; }, 1200);
          break;
        case '/':
          e.preventDefault();
          setIsPaletteOpen(true);
          break;
        case '?':
          e.preventDefault();
          setIsShortcutsOpen(prev => !prev);
          break;
        case 't':
          setTheme(theme === 'dark' ? 'light' : 'dark');
          break;
        case 'd':
          setDensity(density === 'compact' ? 'comfortable' : 'compact');
          break;
        case 'w':
          setWallboard(!wallboard);
          break;
        case 'n':
          setIsNotificationsOpen(prev => !prev);
          break;
        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [navigate, theme, setTheme, density, setDensity, wallboard, setWallboard]);

  // Map route to title & section
  const getPageMeta = (pathname: string) => {
    if (pathname.startsWith('/dashboard')) return { title: 'Network Operational Overview', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/live-map')) return { title: 'Live GIS Operations Map', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/intersections')) return { title: 'Intersections & Junction Topologies', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/signals')) return { title: 'Signal Controllers & NEMA Dual-Ring TS2', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/corridors')) return { title: 'Arterial Corridors & Coordinated Progression', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/cameras')) return { title: 'Edge RTSP Video Telemetry & Detection', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/sensors')) return { title: 'Inductive Loop & Radar Telemetry', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/incidents')) return { title: 'Active Incidents & Lane Closure Console', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/emergency')) return { title: 'Emergency Vehicle Preemption (EVP)', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/transit')) return { title: 'Transit Signal Priority (TSP)', section: 'COMMAND CENTER' };
    if (pathname.startsWith('/predictions')) return { title: 'Arrival Demand & Queue Prediction Models', section: 'INTELLIGENCE' };
    if (pathname.startsWith('/analytics')) return { title: 'Performance Analytics & Level of Service', section: 'INTELLIGENCE' };
    if (pathname.startsWith('/ai-copilot')) return { title: 'AI Engineering Copilot (MUTCD 4D Grounded)', section: 'INTELLIGENCE' };
    if (pathname.startsWith('/devices')) return { title: 'Hardware Infrastructure & Device Registry', section: 'INFRASTRUCTURE' };
    if (pathname.startsWith('/maintenance')) return { title: 'Field Maintenance & Cabinet Work Orders', section: 'INFRASTRUCTURE' };
    if (pathname.startsWith('/audit')) return { title: 'Tamper-Evident Security & Audit Trail', section: 'GOVERNANCE' };
    if (pathname.startsWith('/settings')) return { title: 'System Configuration & Hardware Wizards', section: 'INFRASTRUCTURE' };
    if (pathname.startsWith('/users')) return { title: 'Operator Access Control & RBAC', section: 'GOVERNANCE' };
    if (pathname.startsWith('/provider-health')) return { title: 'Provider Health & Stream Diagnostics', section: 'INFRASTRUCTURE' };
    if (pathname.startsWith('/alert-rules')) return { title: 'Alert & Rules Engine', section: 'INTELLIGENCE' };
    if (pathname.startsWith('/optimizer')) return { title: 'Signal Timing Optimiser & Scenario Sandbox', section: 'INTELLIGENCE' };
    if (pathname.startsWith('/governance')) return { title: 'Audit Ledger, Access Model & API Keys', section: 'GOVERNANCE' };
    if (pathname.startsWith('/data-trust')) return { title: 'Data Trust & Change Verification', section: 'INTELLIGENCE' };
    if (pathname.startsWith('/stringline')) return { title: 'Corridor Stringline (Time-Space Diagram)', section: 'INTELLIGENCE' };
    if (pathname.startsWith('/handover')) return { title: 'Shift Handover', section: 'OPERATIONS' };
    return { title: 'Traffic Operations Platform', section: 'TOC OPERATIONS' };
  };

  const pageMeta = getPageMeta(location.pathname);

  const dbStatus: string | null = systemStatus?.subsystems?.database?.status ?? null;
  const dbDialect: string | null = systemStatus?.subsystems?.database?.dialect ?? null;
  const schemaCurrent: boolean | null = systemStatus?.subsystems?.database?.schema_current ?? null;

  return (
    <div className="app-container">
      {/* Collapsible Left Sidebar */}
      <aside className={`app-sidebar ${isCollapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <NavLink to="/dashboard" className="sidebar-brand-group">
            <div className="sidebar-logo">
              <Layers size={18} />
            </div>
            <div className="sidebar-brand-text">
              <div className="sidebar-brand-title">TRAFFICINTEL</div>
              <div className="sidebar-brand-tagline">TOC CONTROL CENTER</div>
            </div>
          </NavLink>

          <button
            className="sidebar-collapse-btn"
            onClick={toggleSidebar}
            title={isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
          >
            {isCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>

        {/* Navigation IA Grouping */}
        {/* Streamlined Professional Navigation */}
        <nav className="sidebar-nav">
          <div className="nav-group-title">Command Center</div>
          <NavLink to="/dashboard" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Dashboard">
            <Activity size={16} />
            <span>Dashboard</span>
          </NavLink>
          <NavLink to="/live-map" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Live GIS Map">
            <Map size={16} />
            <span>Live GIS Map</span>
          </NavLink>
          <NavLink to="/intersections" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Intersections & Signals">
            <Sliders size={16} />
            <span>Intersections & Signals</span>
          </NavLink>
          <NavLink to="/incidents" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Incident Console">
            <AlertTriangle size={16} />
            <span>Incident Console</span>
            {openIncidentCount > 0 && <span className="nav-badge">{openIncidentCount}</span>}
          </NavLink>
          <NavLink to="/handover" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Shift handover record">
            <ClipboardList size={16} />
            <span>Shift Handover</span>
          </NavLink>

          <div className="nav-group-title">Intelligence & Ops</div>
          <NavLink to="/optimizer" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Signal timing optimiser & scenario sandbox">
            <Calculator size={16} />
            <span>Timing & Scenarios</span>
          </NavLink>
          <NavLink to="/alert-rules" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Alert & rules engine">
            <BellRing size={16} />
            <span>Alert Rules</span>
          </NavLink>
          <NavLink to="/data-trust" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Data trust score & post-change verification">
            <Gauge size={16} />
            <span>Data Trust</span>
          </NavLink>
          <NavLink to="/stringline" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Corridor time-space diagram from observed signal state">
            <Waves size={16} />
            <span>Corridor Stringline</span>
          </NavLink>
          <NavLink to="/ai-copilot" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="AI Operations Copilot">
            <Bot size={16} />
            <span>AI Traffic Copilot</span>
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="System Settings & Health">
            <Settings size={16} />
            <span>Settings & Health</span>
          </NavLink>

          <div className="nav-group-title">Infrastructure & Governance</div>
          <NavLink to="/provider-health" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Provider health & stream diagnostics">
            <HeartPulse size={16} />
            <span>Provider Health</span>
          </NavLink>
          <NavLink to="/governance" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="Audit ledger, access model & API keys">
            <ScrollText size={16} />
            <span>Audit & Access</span>
          </NavLink>
        </nav>

        {/* Operator Status Footer */}
        <div className="sidebar-footer">
          <div className="sidebar-user-info">
            <div className="sidebar-username">{user?.full_name || 'Operator'}</div>
            <div className="sidebar-role-badge">TOC_{user?.role || 'OPERATOR'}</div>
          </div>
          <button
            onClick={logout}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--its-text-muted)',
              cursor: 'pointer',
              padding: '6px',
              borderRadius: 'var(--radius-sm)'
            }}
            title="Sign Out"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      {/* Main Operations Frame */}
      <main className="app-main">
        {/* Top Command Bar */}
        <header className="app-topbar">
          <div className="topbar-left">
            <div className="topbar-title-section">
              <span className="topbar-badge-context">{pageMeta.section}</span>
              <span className="topbar-page-title">{pageMeta.title}</span>
            </div>
          </div>

          {/* Center: Global Search / Command Palette trigger */}
          <button className="global-search-trigger" onClick={() => setIsPaletteOpen(true)}>
            <Search size={14} />
            <span>Search network entities...</span>
            <kbd className="search-shortcut-kbd">Ctrl K</kbd>
          </button>

          {/* Right: Telemetry Streams, Alerts, Safety State */}
          <div className="topbar-right">
            {/* Stream health. An open socket is not the same claim as live
                data, so the badge reports the socket state and the age of the
                last real event separately. */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: 'var(--text-xs)',
                fontFamily: 'var(--font-mono)',
                padding: '4px 8px',
                borderRadius: 'var(--radius-sm)',
                background: wsConnected ? 'var(--its-signal-green-bg)' : 'var(--its-stale-bg)',
                border: `1px solid ${wsConnected ? 'var(--its-signal-green-border)' : 'var(--its-border-subtle)'}`,
                color: wsConnected ? 'var(--its-signal-green)' : 'var(--its-text-muted)'
              }}
              title={
                wsConnected
                  ? lastEventAt
                    ? `Event stream connected. Last event ${formatAge(lastEventAge)} ago.`
                    : 'Event stream connected. No events received this session - a quiet network produces no events.'
                  : `Event stream ${connection.toLowerCase()}.`
              }
            >
              {wsConnected ? <Wifi size={13} /> : <WifiOff size={13} />}
              <span>
                {connection === 'CONNECTED'
                  ? lastEventAt ? `LIVE - ${formatAge(lastEventAge)}` : 'CONNECTED - QUIET'
                  : connection}
              </span>
            </div>

            {/* Safety engine: an architectural property, not a liveness reading.
                Every signal command and preemption call is validated before it
                can reach a controller adapter, so this is stated as a routing
                fact rather than dressed up as a monitored green light. */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                fontSize: 'var(--text-2xs)',
                fontFamily: 'var(--font-mono)',
                fontWeight: 600,
                padding: '4px 8px',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--its-bg-subsurface)',
                border: '1px solid var(--its-border-default)',
                color: 'var(--its-text-secondary)'
              }}
              title="All signal commands and preemption calls are validated by the Deterministic Safety Engine (NEMA TS2 dual-ring conflict matrix, minimum green, clearance, command freshness) before reaching any controller adapter."
            >
              <ShieldCheck size={13} />
              <span>COMMANDS ROUTED VIA SAFETY ENGINE</span>
            </div>

            {/* Display preferences */}
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="its-btn"
              style={iconBtn}
              title={`Theme: ${theme}. Press T to toggle.`}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            >
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </button>

            <button
              onClick={() => setDensity(density === 'compact' ? 'comfortable' : 'compact')}
              className="its-btn"
              style={iconBtn}
              title={`Density: ${density}. Press D to toggle.`}
              aria-label={`Switch to ${density === 'compact' ? 'comfortable' : 'compact'} density`}
              aria-pressed={density === 'compact'}
            >
              <Rows3 size={14} />
            </button>

            <button
              onClick={() => setWallboard(!wallboard)}
              className="its-btn"
              style={{
                ...iconBtn,
                borderColor: wallboard ? 'var(--its-border-focused)' : undefined,
                color: wallboard ? 'var(--its-text-accent)' : undefined,
              }}
              title="Wallboard mode for control-room displays. Press W."
              aria-label="Toggle wallboard mode"
              aria-pressed={wallboard}
            >
              <MonitorPlay size={14} />
            </button>

            <button
              onClick={() => setIsShortcutsOpen(true)}
              className="its-btn"
              style={iconBtn}
              title="Keyboard shortcuts"
              aria-label="Show keyboard shortcuts"
            >
              <Keyboard size={14} />
            </button>

            {/* Notification centre */}
            <button
              onClick={() => setIsNotificationsOpen(true)}
              style={{
                position: 'relative',
                background: 'var(--its-bg-elevated)',
                border: '1px solid var(--its-border-default)',
                color: unreadCount > 0 ? 'var(--its-signal-red)' : 'var(--its-text-secondary)',
                width: '32px',
                height: '32px',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer'
              }}
              title="Notification centre. Press N."
              aria-label={`Notification centre, ${unreadCount} unread`}
            >
              <Bell size={15} />
              {unreadCount > 0 && (
                <span
                  style={{
                    position: 'absolute',
                    top: '-4px',
                    right: '-4px',
                    background: 'var(--its-signal-red)',
                    color: '#ffffff',
                    borderRadius: '50%',
                    minWidth: '16px',
                    height: '16px',
                    fontSize: '10px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 'bold',
                  }}
                >
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </button>
          </div>
        </header>

        {/* Industrial Status Strip */}
        <div className="system-status-strip">
          <div className="status-strip-nodes">
            {/* Every indicator below reflects a measurement this session made.
                Unknown is shown as unknown rather than defaulting to green. */}
            <div className="status-node-item">
              <span className={`status-dot ${apiReachable === null ? '' : apiReachable ? 'active' : 'warn'}`}></span>
              <span>
                REST API: {apiReachable === null ? 'CHECKING' : apiReachable ? 'RESPONDING' : 'UNREACHABLE'}
              </span>
            </div>
            <div className="status-node-item">
              <span className={`status-dot ${dbStatus === null ? '' : dbStatus === 'CONNECTED' ? 'active' : 'warn'}`}></span>
              <span>
                DATABASE{dbDialect ? ` (${dbDialect.toUpperCase()})` : ''}: {dbStatus ?? 'UNKNOWN'}
              </span>
            </div>
            <div className="status-node-item">
              <span className={`status-dot ${wsConnected ? 'active' : 'warn'}`}></span>
              <span>
                WS TELEMETRY: {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
                {wsConnected && ` • LAST EVENT: ${lastEventAt ? new Date(lastEventAt).toUTCString().slice(17, 25) : 'NONE YET'}`}
              </span>
            </div>
            {droppedEvents > 0 && (
              <div className="status-node-item">
                <span className="status-dot warn"></span>
                <span title="This console fell behind and the server discarded queued events. Refresh to resynchronise.">
                  STREAM GAP: {droppedEvents} EVENTS DROPPED
                </span>
              </div>
            )}
            {schemaCurrent === false && (
              <div className="status-node-item">
                <span className="status-dot warn"></span>
                <span>SCHEMA: MIGRATION PENDING</span>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--its-text-muted)' }}>
            <Clock size={12} />
            <span>{utcTime || 'SYNCHRONIZING UTC...'}</span>
          </div>
        </div>

        {/* Page Content Body */}
        <div className="page-content">
          <Outlet />
        </div>
      </main>

      {/* Global modals, drawers and the toast stack */}
      <CommandPalette
        isOpen={isPaletteOpen}
        onClose={() => setIsPaletteOpen(false)}
        onOpenCommandWorkflow={(controllerId) => setCommandControllerId(controllerId)}
        onOpenWizard={() => setIsWizardOpen(true)}
      />

      <NotificationCenter
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
      />

      <ShortcutsSheet isOpen={isShortcutsOpen} onClose={() => setIsShortcutsOpen(false)} />

      {commandControllerId !== undefined && (
        <SignalCommandWorkflow
          controllers={controllers}
          preselectedControllerId={commandControllerId}
          onClose={() => setCommandControllerId(undefined)}
          onExecuted={(result) =>
            notify({
              severity: result.status === 'EXECUTED' ? 'INFO' : 'WARNING',
              title: `Signal command ${result.status}`,
              detail: `Phase ${result.requested_phase} - safety ${result.safety_check_passed ? 'passed' : 'rejected'}`,
              origin: 'operator.action',
              link: '/signals',
            })
          }
        />
      )}

      {isWizardOpen && (
        <OnboardingWizard
          onClose={() => setIsWizardOpen(false)}
          onComplete={() => navigate('/live-map')}
        />
      )}

      <ToastStack />
    </div>
  );
};

const iconBtn: React.CSSProperties = {
  width: '32px',
  height: '32px',
  padding: 0,
  justifyContent: 'center',
};
