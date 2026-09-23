import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, Bell, CheckCheck, Info, ShieldAlert, Trash2, X,
} from 'lucide-react';
import { useConsole } from '../context/ConsoleContext';
import type { Notification, NotificationSeverity } from '../context/ConsoleContext';
import { formatAge, formatTimestamp } from '../lib/quality';
import { useTickingAge } from '../hooks/useTickingAge';

/**
 * Toast stack + notification centre.
 *
 * Both are driven exclusively by events the backend actually emitted. Nothing
 * here fires on a timer or synthesises activity to make the console look busy:
 * a quiet control room produces an empty notification centre, and that is the
 * correct reading of a quiet network.
 */

const SEVERITY_ICON: Record<NotificationSeverity, React.ReactNode> = {
  CRITICAL: <ShieldAlert size={15} />,
  WARNING: <AlertTriangle size={15} />,
  INFO: <Info size={15} />,
};

const SEVERITY_COLOR: Record<NotificationSeverity, string> = {
  CRITICAL: 'var(--its-signal-red)',
  WARNING: 'var(--its-signal-yellow)',
  INFO: 'var(--its-text-accent)',
};

const TOAST_TTL_MS = 8000;

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------

export const ToastStack: React.FC = () => {
  const { notifications, dismiss } = useConsole();
  const [visible, setVisible] = useState<string[]>([]);

  // Only genuinely new notifications toast; opening the drawer must not
  // re-announce everything the operator has already seen.
  useEffect(() => {
    const newest = notifications[0];
    if (!newest || newest.read) return;

    setVisible(prev => (prev.includes(newest.id) ? prev : [newest.id, ...prev].slice(0, 4)));
    const timer = setTimeout(
      () => setVisible(prev => prev.filter(id => id !== newest.id)),
      TOAST_TTL_MS,
    );
    return () => clearTimeout(timer);
  }, [notifications]);

  const shown = notifications.filter(n => visible.includes(n.id));
  if (shown.length === 0) return null;

  return (
    <div className="toast-stack" role="region" aria-label="Recent alerts">
      {shown.map(n => (
        <div key={n.id} className={`toast severity-${n.severity}`} role="alert">
          <span style={{ color: SEVERITY_COLOR[n.severity], marginTop: '1px' }}>
            {SEVERITY_ICON[n.severity]}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
              {n.title}
            </div>
            {n.detail && (
              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
                {n.detail}
              </div>
            )}
            <div
              className="mono"
              style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}
            >
              {n.origin}
            </div>
          </div>
          <button
            onClick={() => {
              setVisible(prev => prev.filter(id => id !== n.id));
              dismiss(n.id);
            }}
            aria-label={`Dismiss alert: ${n.title}`}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: 'var(--its-text-muted)', padding: '2px',
            }}
          >
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Notification centre
// ---------------------------------------------------------------------------

const NotificationRow: React.FC<{
  notification: Notification;
  onOpen: (n: Notification) => void;
  onDismiss: (id: string) => void;
}> = ({ notification, onOpen, onDismiss }) => {
  const age = useTickingAge(notification.timestamp);

  return (
    <div
      style={{
        display: 'flex',
        gap: '10px',
        padding: '10px 12px',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--its-border-subtle)',
        background: notification.read ? 'transparent' : 'var(--its-bg-subsurface)',
        alignItems: 'flex-start',
      }}
    >
      <span style={{ color: SEVERITY_COLOR[notification.severity], marginTop: '1px' }}>
        {SEVERITY_ICON[notification.severity]}
      </span>

      <button
        onClick={() => onOpen(notification)}
        style={{
          flex: 1, minWidth: 0, background: 'transparent', border: 'none',
          textAlign: 'left', cursor: notification.link ? 'pointer' : 'default', padding: 0,
        }}
      >
        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
          {notification.title}
        </div>
        {notification.detail && (
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            {notification.detail}
          </div>
        )}
        <div
          className="mono"
          style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginTop: '4px' }}
          title={formatTimestamp(notification.timestamp)}
        >
          {notification.origin} · {formatAge(age)} ago
        </div>
      </button>

      <button
        onClick={() => onDismiss(notification.id)}
        aria-label={`Dismiss: ${notification.title}`}
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--its-text-muted)', padding: '2px',
        }}
      >
        <X size={13} />
      </button>
    </div>
  );
};

export const NotificationCenter: React.FC<{ isOpen: boolean; onClose: () => void }> = ({
  isOpen,
  onClose,
}) => {
  const { notifications, markRead, markAllRead, dismiss, clearAll, connection, lastEventAt } =
    useConsole();
  const [filter, setFilter] = useState<'ALL' | NotificationSeverity>('ALL');
  const navigate = useNavigate();
  const lastEventAge = useTickingAge(lastEventAt);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  const filtered = useMemo(
    () => (filter === 'ALL' ? notifications : notifications.filter(n => n.severity === filter)),
    [notifications, filter],
  );

  if (!isOpen) return null;

  const handleOpen = (n: Notification) => {
    markRead(n.id);
    if (n.link) {
      navigate(n.link);
      onClose();
    }
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside
        className="junction-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Notification centre"
      >
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Bell size={17} color="var(--its-text-accent)" />
            <span
              style={{
                fontSize: 'var(--text-sm)', fontWeight: 700,
                letterSpacing: '0.04em', color: 'var(--its-text-primary)',
              }}
            >
              NOTIFICATION CENTRE
            </span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close notification centre"
            style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--its-text-muted)' }}
          >
            <X size={17} />
          </button>
        </div>

        {/* Stream health: the centre is only as live as the stream feeding it. */}
        <div
          style={{
            padding: '8px 16px',
            borderBottom: '1px solid var(--its-border-subtle)',
            fontSize: 'var(--text-2xs)',
            color: 'var(--its-text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          STREAM: {connection}
          {lastEventAt
            ? ` · LAST EVENT ${formatAge(lastEventAge)} AGO`
            : ' · NO EVENTS RECEIVED THIS SESSION'}
        </div>

        <div
          style={{
            display: 'flex', gap: '6px', padding: '10px 16px',
            borderBottom: '1px solid var(--its-border-subtle)', flexWrap: 'wrap',
          }}
        >
          {(['ALL', 'CRITICAL', 'WARNING', 'INFO'] as const).map(level => (
            <button
              key={level}
              onClick={() => setFilter(level)}
              className="its-btn"
              aria-pressed={filter === level}
              style={{
                fontSize: '10px', padding: '3px 8px',
                borderColor: filter === level ? 'var(--its-border-focused)' : undefined,
                color: filter === level ? 'var(--its-text-accent)' : undefined,
              }}
            >
              {level}
              {level !== 'ALL' && ` (${notifications.filter(n => n.severity === level).length})`}
            </button>
          ))}

          <div style={{ flex: 1 }} />

          <button onClick={markAllRead} className="its-btn" style={{ fontSize: '10px', padding: '3px 8px' }}>
            <CheckCheck size={11} />
            <span>Mark all read</span>
          </button>
          <button onClick={clearAll} className="its-btn" style={{ fontSize: '10px', padding: '3px 8px' }}>
            <Trash2 size={11} />
            <span>Clear</span>
          </button>
        </div>

        <div className="junction-drawer-body">
          {filtered.length === 0 ? (
            <div
              style={{
                textAlign: 'center', padding: '40px 20px',
                color: 'var(--its-text-muted)', fontSize: 'var(--text-xs)', lineHeight: 1.6,
              }}
            >
              <Bell size={28} style={{ marginBottom: '10px', opacity: 0.4 }} />
              <div style={{ fontWeight: 700, marginBottom: '4px' }}>
                {filter === 'ALL' ? 'NO NOTIFICATIONS' : `NO ${filter} NOTIFICATIONS`}
              </div>
              <div>
                Notifications appear when the backend emits a real event. An empty
                centre means nothing has been reported this session.
              </div>
            </div>
          ) : (
            filtered.map(n => (
              <NotificationRow
                key={n.id}
                notification={n}
                onOpen={handleOpen}
                onDismiss={dismiss}
              />
            ))
          )}
        </div>
      </aside>
    </>
  );
};
