"use client";

import { useEffect, useRef, useState, useCallback } from "react";

interface WsEvent {
  event: string;
  project: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export function useWebSocket() {
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const listenersRef = useRef<Map<string, Set<(data: WsEvent) => void>>>(new Map());

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8472/ws");
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      try {
        const event: WsEvent = JSON.parse(msg.data);
        setLastEvent(event);
        const typeListeners = listenersRef.current.get(event.event);
        if (typeListeners) {
          typeListeners.forEach((fn) => fn(event));
        }
        const projListeners = listenersRef.current.get(`project:${event.project}`);
        if (projListeners) {
          projListeners.forEach((fn) => fn(event));
        }
      } catch {}
    };

    return () => ws.close();
  }, []);

  const subscribe = useCallback(
    (key: string, fn: (data: WsEvent) => void) => {
      if (!listenersRef.current.has(key)) {
        listenersRef.current.set(key, new Set());
      }
      listenersRef.current.get(key)!.add(fn);
      return () => {
        listenersRef.current.get(key)?.delete(fn);
      };
    },
    []
  );

  return { lastEvent, connected, subscribe };
}
