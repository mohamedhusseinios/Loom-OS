"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

interface WsEvent {
  event: string;
  project: string;
  data: Record<string, unknown>;
  timestamp: string;
}

type Listener = (event: WsEvent) => void;

interface WebSocketContextValue {
  lastEvent: WsEvent | null;
  connected: boolean;
  subscribe: (key: string, fn: Listener) => () => void;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

// Pinned to 127.0.0.1 (not "localhost") on purpose: the daemon binds IPv4 only
// (`--host 127.0.0.1`). On dual-stack machines "localhost" can resolve to ::1
// first, and some browsers don't fall back to IPv4 for a WebSocket the way they
// do for fetch() — so the socket would silently fail while REST still worked.
const WS_URL = "ws://127.0.0.1:8472/ws";

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const [connected, setConnected] = useState(false);
  // Listeners keyed by event type ("agent:dispatched") or by project
  // ("project:<id>"). Stored in a ref so it's stable across renders and
  // doesn't trigger reconnects.
  const listenersRef = useRef<Map<string, Set<Listener>>>(new Map());

  useEffect(() => {
    // Single shared connection for the whole app. Previously each component
    // calling useWebSocket() opened its own socket — Sidebar + ProjectsPage +
    // each project page = 2-3 concurrent connections and reconnect storms on
    // navigation.
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let unmounted = false;

    const connect = () => {
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        attempts = 0;
        setConnected(true);
      };

      ws.onmessage = (msg) => {
        try {
          const event: WsEvent = JSON.parse(msg.data);
          setLastEvent(event);
          const typeListeners = listenersRef.current.get(event.event);
          typeListeners?.forEach((fn) => fn(event));
          const projListeners = listenersRef.current.get(`project:${event.project}`);
          projListeners?.forEach((fn) => fn(event));
        } catch {
          // malformed frame — ignore
        }
      };

      // A dropped socket (daemon restart, laptop sleep/wake, idle timeout) used
      // to stay dead until a manual page refresh — the cause of "the dashboard
      // only updates after I reload". Reconnect with capped exponential backoff
      // instead. `onclose` fires after a failed connection too, so it is the
      // single place reconnection is scheduled. Listeners live in a ref, so all
      // existing subscriptions keep working across reconnects.
      ws.onclose = () => {
        setConnected(false);
        if (unmounted) return;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        attempts += 1;
        const delay = Math.min(1000 * 2 ** (attempts - 1), 10000);
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      unmounted = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  const subscribe = useCallback((key: string, fn: Listener) => {
    let set = listenersRef.current.get(key);
    if (!set) {
      set = new Set();
      listenersRef.current.set(key, set);
    }
    set.add(fn);
    return () => {
      set?.delete(fn);
    };
  }, []);

  const value = useMemo<WebSocketContextValue>(
    () => ({ lastEvent, connected, subscribe }),
    [lastEvent, connected, subscribe]
  );

  return <WebSocketContext.Provider value={value}>{children}</WebSocketContext.Provider>;
}

export function useWebSocket(): WebSocketContextValue {
  const ctx = useContext(WebSocketContext);
  if (!ctx) {
    throw new Error("useWebSocket must be used within a <WebSocketProvider>");
  }
  return ctx;
}

export type { WsEvent };
