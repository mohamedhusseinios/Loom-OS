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

const WS_URL = "ws://localhost:8472/ws";

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
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
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

    return () => ws.close();
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
