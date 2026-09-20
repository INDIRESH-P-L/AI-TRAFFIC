import React, { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
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
  Layers
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { CommandPalette } from './CommandPalette';
import { AlertDrawer } from './AlertDrawer';
import { api } from '../api/client';

export const Layout: React.FC = () => {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [wsConnected, setWsConnected] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    return localStorage.getItem('toc_sidebar_collapsed') === 'true';
  });
  const [isPaletteOpen, setIsPaletteOpen] = useState(false);
  const [isAlertDrawerOpen, setIsAlertDrawerOpen] = useState(false);
  const [unreadAlertCount, setUnreadAlertCount] = useState(0);
  const [utcTime, setUtcTime] = useState('');

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
    const fetchAlertCount = () => {
      api.getDashboardSummary()
        .then(summary => {
          const alerts = summary.alerts?.unacknowledged_count || 0;
          const incidents = summary.incidents?.active_count || 0;
          setUnreadAlertCount(alerts + incidents);
        })
        .catch(() => {});
    };
    fetchAlertCount();
    const interval = setInterval(fetchAlertCount, 15000);
    return () => clearInterval(interval);
  }, []);

  // Connect to real WebSocket gateway
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/ws`;
    let socket: WebSocket | null = null;

    try {
      socket = new WebSocket(wsUrl);
      socket.onopen = () => setWsConnected(true);
      socket.onclose = () => setWsConnected(false);
      socket.onerror = () => setWsConnected(false);
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'incident.detected' || payload.type === 'safety.alarm') {
            setUnreadAlertCount(prev => prev + 1);
          }
        } catch {
          // ignore parsing error
        }
      };
    } catch {
      setWsConnected(false);
    }

    return () => {
      if (socket) socket.close();
    };
  }, []);

  // Toggle sidebar collapse
  const toggleSidebar = () => {
    setIsCollapsed(prev => {
      const next = !prev;
      localStorage.setItem('toc_sidebar_collapsed', String(next));
      return next;
    });
  };

  // Keyboard shortcut Ctrl+K or / for command palette
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setIsPaletteOpen(prev => !prev);
      } else if (e.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault();
        setIsPaletteOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

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
    return { title: 'Traffic Operations Platform', section: 'TOC OPERATIONS' };
  };

  const pageMeta = getPageMeta(location.pathname);

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
            {unreadAlertCount > 0 && <span className="nav-badge">{unreadAlertCount}</span>}
          </NavLink>

          <div className="nav-group-title">Intelligence & Ops</div>
          <NavLink to="/ai-copilot" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="AI Operations Copilot">
            <Bot size={16} />
            <span>AI Traffic Copilot</span>
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="System Settings & Health">
            <Settings size={16} />
            <span>Settings & Health</span>
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
            {/* WebSocket Indicator */}
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
                color: wsConnected ? '#34d399' : 'var(--its-text-muted)'
              }}
              title={wsConnected ? 'Real-time WebSocket Gateway Connected' : 'WebSocket Gateway Disconnected'}
            >
              {wsConnected ? <Wifi size={13} /> : <WifiOff size={13} />}
              <span>{wsConnected ? 'LIVE FEED' : 'OFFLINE'}</span>
            </div>

            {/* Safety Engine Badge */}
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
                background: 'rgba(56, 189, 248, 0.1)',
                border: '1px solid rgba(56, 189, 248, 0.3)',
                color: '#38bdf8'
              }}
              title="Deterministic NEMA TS2 Dual-Ring Barrier Conflict Interlock"
            >
              <ShieldCheck size={13} />
              <span>SAFETY INTERLOCK: ACTIVE</span>
            </div>

            {/* Alert Drawer Trigger */}
            <button
              onClick={() => setIsAlertDrawerOpen(true)}
              style={{
                position: 'relative',
                background: 'var(--its-bg-elevated)',
                border: '1px solid var(--its-border-default)',
                color: unreadAlertCount > 0 ? '#f87171' : 'var(--its-text-secondary)',
                width: '32px',
                height: '32px',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer'
              }}
              title="Inspect Alerts & Incidents"
            >
              <Bell size={15} />
              {unreadAlertCount > 0 && (
                <span
                  style={{
                    position: 'absolute',
                    top: '-4px',
                    right: '-4px',
                    background: '#ef4444',
                    color: '#ffffff',
                    borderRadius: '50%',
                    width: '16px',
                    height: '16px',
                    fontSize: '10px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 'bold',
                    boxShadow: '0 0 6px rgba(239, 68, 68, 0.6)'
                  }}
                >
                  {unreadAlertCount}
                </span>
              )}
            </button>
          </div>
        </header>

        {/* Industrial Status Strip */}
        <div className="system-status-strip">
          <div className="status-strip-nodes">
            <div className="status-node-item">
              <span className="status-dot active"></span>
              <span>REST API: v1 ONLINE</span>
            </div>
            <div className="status-node-item">
              <span className="status-dot active"></span>
              <span>POSTGRES / SQLITE: READY</span>
            </div>
            <div className="status-node-item">
              <span className={`status-dot ${wsConnected ? 'active' : 'warn'}`}></span>
              <span>WS TELEMETRY: {wsConnected ? 'SYNCHRONIZED' : 'RETRYING'}</span>
            </div>
            <div className="status-node-item">
              <span className="status-dot active"></span>
              <span>NEMA TS2 ENGINE: RIGID</span>
            </div>
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

      {/* Global Modals & Drawers */}
      <CommandPalette isOpen={isPaletteOpen} onClose={() => setIsPaletteOpen(false)} />
      <AlertDrawer isOpen={isAlertDrawerOpen} onClose={() => setIsAlertDrawerOpen(false)} />
    </div>
  );
};
