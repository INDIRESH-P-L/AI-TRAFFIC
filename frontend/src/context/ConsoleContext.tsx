import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useEventStream } from '../hooks/useEventStream';
import { clientId } from '../lib/entropy';
import type { ConnectionState, StreamEvent } from '../hooks/useEventStream';

/**
 * TRAFFICINTEL AI - Console shell state
 *
 * One provider for the things every page needs: the shared real-time stream,
 * operator display preferences, and the notification centre.
 *
 * Preferences persist in localStorage because they are per-viewer conveniences
 * (a night-shift operator's theme is not an agency-wide setting). Every access
 * is guarded: a locked-down browser must degrade to defaults, not a blank
 * console.
 */

export type ThemeMode = 'light' | 'dark' | 'system';
export type Density = 'comfortable' | 'compact';

export type NotificationSeverity = 'INFO' | 'WARNING' | 'CRITICAL';

export interface Notification {
  id: string;
  severity: NotificationSeverity;
  title: string;
  detail?: string;
  timestamp: string;
  read: boolean;
  /** Where this came from: a live event topic, or an action the operator took. */
  origin: string;
  link?: string;
}

interface ConsoleContextValue {
  // Real-time stream
  connection: ConnectionState;
  lastEventAt: string | null;
  eventCount: number;
  reconnectAttempt: number;
  droppedEvents: number;
  subscribe: (topic: string, handler: (event: StreamEvent) => void) => () => void;

  // Preferences
  theme: ThemeMode;
  setTheme: (mode: ThemeMode) => void;
  resolvedTheme: 'light' | 'dark';
  density: Density;
  setDensity: (density: Density) => void;
  wallboard: boolean;
  setWallboard: (on: boolean) => void;

  // Notification centre
  notifications: Notification[];
  unreadCount: number;
  notify: (n: Omit<Notification, 'id' | 'timestamp' | 'read'>) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  dismiss: (id: string) => void;
  clearAll: () => void;
}

const ConsoleContext = createContext<ConsoleContextValue | undefined>(undefined);

const STORAGE_KEYS = {
  theme: 'trafficintel_theme',
  density: 'trafficintel_density',
  wallboard: 'trafficintel_wallboard',
};

function readStorage<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    // Private windows and locked-down profiles throw on access.
    return fallback;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Preference simply will not persist; the session still works.
  }
}

/** Events promoted into the notification centre, with their severity. */
const NOTIFIABLE: Record<string, { severity: NotificationSeverity; link?: string }> = {
  'incident.detected': { severity: 'CRITICAL', link: '/incidents' },
  'incident.updated': { severity: 'INFO', link: '/incidents' },
  'signal.updated': { severity: 'INFO', link: '/signals' },
  'safety.alarm': { severity: 'CRITICAL', link: '/signals' },
  'provider.health.degraded': { severity: 'WARNING', link: '/settings' },
};

const MAX_NOTIFICATIONS = 100;

export const ConsoleProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const stream = useEventStream(true);

  const [theme, setThemeState] = useState<ThemeMode>(() =>
    readStorage<ThemeMode>(STORAGE_KEYS.theme, 'system'));
  const [density, setDensityState] = useState<Density>(() =>
    readStorage<Density>(STORAGE_KEYS.density, 'comfortable'));
  const [wallboard, setWallboardState] = useState<boolean>(() =>
    readStorage<string>(STORAGE_KEYS.wallboard, 'false') === 'true');

  const [systemDark, setSystemDark] = useState<boolean>(() => {
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches;
    } catch {
      return false;
    }
  });

  const [notifications, setNotifications] = useState<Notification[]>([]);

  // --- Theme ------------------------------------------------------------
  useEffect(() => {
    let media: MediaQueryList;
    try {
      media = window.matchMedia('(prefers-color-scheme: dark)');
    } catch {
      return;
    }
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const resolvedTheme: 'light' | 'dark' =
    theme === 'system' ? (systemDark ? 'dark' : 'light') : theme;

  useEffect(() => {
    const root = document.documentElement;
    // An explicit choice stamps the attribute; 'system' removes it so the
    // prefers-color-scheme media query is the only thing deciding.
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute('data-density', density);
  }, [density]);

  useEffect(() => {
    document.documentElement.toggleAttribute('data-wallboard', wallboard);
  }, [wallboard]);

  const setTheme = useCallback((mode: ThemeMode) => {
    setThemeState(mode);
    writeStorage(STORAGE_KEYS.theme, mode);
  }, []);

  const setDensity = useCallback((next: Density) => {
    setDensityState(next);
    writeStorage(STORAGE_KEYS.density, next);
  }, []);

  const setWallboard = useCallback((on: boolean) => {
    setWallboardState(on);
    writeStorage(STORAGE_KEYS.wallboard, String(on));
  }, []);

  // --- Notifications ----------------------------------------------------
  const notify = useCallback((n: Omit<Notification, 'id' | 'timestamp' | 'read'>) => {
    setNotifications(prev => [
      {
        ...n,
        id: clientId('notif'),
        timestamp: new Date().toISOString(),
        read: false,
      },
      ...prev,
    ].slice(0, MAX_NOTIFICATIONS));
  }, []);

  const markRead = useCallback((id: string) => {
    setNotifications(prev => prev.map(n => (n.id === id ? { ...n, read: true } : n)));
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  }, []);

  const dismiss = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const clearAll = useCallback(() => setNotifications([]), []);

  // Promote real stream events into the notification centre. Only events the
  // backend actually emitted appear here - nothing is generated on a timer.
  const { subscribe } = stream;
  useEffect(() => {
    return subscribe('*', (envelope) => {
      const rule = NOTIFIABLE[envelope.event];
      if (!rule) return;

      const payload = envelope.payload || {};
      const title =
        payload.title ||
        payload.name ||
        envelope.event.replace(/[._]/g, ' ').toUpperCase();

      const detailParts = Object.entries(payload)
        .filter(([key]) => key !== 'title')
        .slice(0, 3)
        .map(([key, value]) => `${key}: ${value}`);

      notify({
        severity: rule.severity,
        title: String(title),
        detail: detailParts.join(' · ') || undefined,
        origin: envelope.event,
        link: rule.link,
      });
    });
  }, [subscribe, notify]);

  const value = useMemo<ConsoleContextValue>(() => ({
    connection: stream.state,
    lastEventAt: stream.lastEventAt,
    eventCount: stream.eventCount,
    reconnectAttempt: stream.reconnectAttempt,
    droppedEvents: stream.droppedEvents,
    subscribe: stream.subscribe,
    theme,
    setTheme,
    resolvedTheme,
    density,
    setDensity,
    wallboard,
    setWallboard,
    notifications,
    unreadCount: notifications.filter(n => !n.read).length,
    notify,
    markRead,
    markAllRead,
    dismiss,
    clearAll,
  }), [
    stream.state, stream.lastEventAt, stream.eventCount, stream.reconnectAttempt,
    stream.droppedEvents, stream.subscribe,
    theme, setTheme, resolvedTheme, density, setDensity, wallboard, setWallboard,
    notifications, notify, markRead, markAllRead, dismiss, clearAll,
  ]);

  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>;
};

export const useConsole = (): ConsoleContextValue => {
  const context = useContext(ConsoleContext);
  if (!context) throw new Error('useConsole must be used within a ConsoleProvider');
  return context;
};
