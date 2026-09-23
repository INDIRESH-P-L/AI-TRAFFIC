import { useCallback, useEffect, useRef, useState } from 'react';
import { jitterFraction } from '../lib/entropy';
import { getAuthToken } from '../api/client';

/**
 * TRAFFICINTEL AI - Real-time event stream
 *
 * One typed WebSocket client for the whole console, with reconnect backoff and
 * an honest connection-health model.
 *
 * "Connected" here means the socket is open. It deliberately does NOT mean
 * data is flowing: a gateway can hold a socket open while every provider
 * behind it has gone silent. The hook therefore reports `lastEventAt`
 * separately, so the status badge can distinguish "connected, quiet" from
 * "connected, live" instead of implying the former is the latter.
 */

export type ConnectionState = 'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED';

/** Envelope the server sends: { event, timestamp, payload }. */
export interface StreamEvent<T = any> {
  event: string;
  timestamp: string;
  payload: T;
}

export type EventHandler = (event: StreamEvent) => void;

interface UseEventStreamResult {
  state: ConnectionState;
  lastEventAt: string | null;
  lastEvent: StreamEvent | null;
  eventCount: number;
  /** Subscribe to one topic, or '*' for all. Returns an unsubscribe function. */
  subscribe: (topic: string, handler: EventHandler) => () => void;
  reconnectAttempt: number;
  droppedEvents: number;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

export function useEventStream(enabled = true): UseEventStreamResult {
  const [state, setState] = useState<ConnectionState>(enabled ? 'CONNECTING' : 'DISCONNECTED');
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);
  const [lastEvent, setLastEvent] = useState<StreamEvent | null>(null);
  const [eventCount, setEventCount] = useState(0);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  // Non-zero means this client fell behind and the bus discarded events;
  // its view of the stream has a gap.
  const [droppedEvents, setDroppedEvents] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef<Map<string, Set<EventHandler>>>(new Map());
  const retryTimerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const closedByUsRef = useRef(false);

  const subscribe = useCallback((topic: string, handler: EventHandler) => {
    const handlers = handlersRef.current;
    if (!handlers.has(topic)) handlers.set(topic, new Set());
    handlers.get(topic)!.add(handler);

    return () => {
      const set = handlers.get(topic);
      if (!set) return;
      set.delete(handler);
      if (set.size === 0) handlers.delete(topic);
    };
  }, []);

  const dispatch = useCallback((envelope: StreamEvent) => {
    const handlers = handlersRef.current;

    // Exact topic, then wildcard prefixes ('signal.*'), then global ('*').
    const targets: EventHandler[] = [];
    handlers.get(envelope.event)?.forEach(h => targets.push(h));

    const segments = envelope.event.split('.');
    for (let i = segments.length - 1; i > 0; i--) {
      const prefix = `${segments.slice(0, i).join('.')}.*`;
      handlers.get(prefix)?.forEach(h => targets.push(h));
    }
    handlers.get('*')?.forEach(h => targets.push(h));

    targets.forEach(handler => {
      try {
        handler(envelope);
      } catch (err) {
        // A subscriber throwing must not tear down the stream for everyone else.
        console.error('Event handler failed for', envelope.event, err);
      }
    });
  }, []);

  useEffect(() => {
    if (!enabled) {
      setState('DISCONNECTED');
      return;
    }

    closedByUsRef.current = false;

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

      // The gateway authenticates the handshake. Browsers cannot set headers
      // on a WebSocket upgrade, so the token travels as a query parameter -
      // the same bearer token, over the same TLS connection, just in the only
      // place the WebSocket API allows it to go.
      const token = getAuthToken();
      if (!token) {
        // No session yet. Retrying blindly would hammer the gateway with
        // handshakes it must reject, so wait for the next attempt window.
        setState('DISCONNECTED');
        scheduleRetry();
        return;
      }

      const url = `${protocol}//${window.location.host}/api/v1/ws?token=${encodeURIComponent(token)}`;

      let socket: WebSocket;
      try {
        socket = new WebSocket(url);
      } catch {
        scheduleRetry();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        attemptRef.current = 0;
        setReconnectAttempt(0);
        setState('CONNECTED');
      };

      socket.onmessage = (message) => {
        // The gateway answers keepalives with a bare "pong"; only JSON frames
        // are events, and only events advance lastEventAt.
        if (message.data === 'pong') return;
        try {
          const envelope = JSON.parse(message.data) as StreamEvent;
          if (!envelope || typeof envelope.event !== 'string') return;

          // stream.status is a control frame, not an operational event. It
          // must not advance lastEventAt, or a quiet network would look live
          // because the gateway said hello.
          if (envelope.event === 'stream.status') {
            const dropped = Number((envelope.payload as any)?.dropped_events ?? 0);
            if (dropped > 0) setDroppedEvents(dropped);
            dispatch(envelope);
            return;
          }

          setLastEvent(envelope);
          setLastEventAt(envelope.timestamp ?? new Date().toISOString());
          setEventCount(prev => prev + 1);
          dispatch(envelope);
        } catch {
          // Unparseable frame: ignored rather than surfaced as an event.
        }
      };

      socket.onerror = () => {
        // onclose always follows; retry is scheduled there.
      };

      socket.onclose = () => {
        socketRef.current = null;
        if (closedByUsRef.current) {
          setState('DISCONNECTED');
          return;
        }
        scheduleRetry();
      };
    };

    const scheduleRetry = () => {
      attemptRef.current += 1;
      setReconnectAttempt(attemptRef.current);
      setState('RECONNECTING');

      // Exponential backoff with jitter, so a restarted backend does not get
      // hammered by every open console at the same instant.
      const backoff = Math.min(BASE_BACKOFF_MS * 2 ** (attemptRef.current - 1), MAX_BACKOFF_MS);
      const jittered = backoff * (0.7 + jitterFraction() * 0.6);

      retryTimerRef.current = window.setTimeout(connect, jittered);
    };

    connect();

    // Keepalive: proves the path is alive, and keeps intermediaries from
    // silently dropping an idle socket while the badge still says CONNECTED.
    const keepalive = window.setInterval(() => {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send('ping');
      }
    }, 25_000);

    return () => {
      closedByUsRef.current = true;
      window.clearInterval(keepalive);
      if (retryTimerRef.current !== null) window.clearTimeout(retryTimerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [enabled, dispatch]);

  return {
    state, lastEventAt, lastEvent, eventCount, subscribe, reconnectAttempt, droppedEvents,
  };
}
