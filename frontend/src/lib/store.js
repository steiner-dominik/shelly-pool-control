// Auth state + live device snapshot (WebSocket with reconnect + REST fallback).
import { writable } from "svelte/store";
import { api, setCsrf } from "./api.js";

export const auth = writable({ loading: true, authenticated: false,
  setup_required: false, user: null, role: null, simulate: false,
  via_ingress: false });

export const snapshot = writable(null);
export const wsConnected = writable(false);

let ws = null;
let wsTimer = null;
let pollTimer = null;

export async function refreshAuth() {
  try {
    const state = await api.get("/api/auth/state");
    if (state.csrf) setCsrf(state.csrf);
    auth.set({ loading: false, ...state });
    if (state.authenticated) connectLive();
    return state;
  } catch {
    auth.set({ loading: false, authenticated: false, setup_required: false,
      user: null, role: null, simulate: false, via_ingress: false });
    return null;
  }
}

export function roleAtLeast(role, min) {
  const rank = { viewer: 0, operator: 1, admin: 2 };
  return (rank[role] ?? -1) >= rank[min];
}

export function connectLive() {
  if (ws) return;
  openWs();
  // REST fallback keeps the UI alive if WS is blocked by a proxy
  pollTimer = setInterval(async () => {
    let connected;
    wsConnected.update((v) => (connected = v, v));
    if (!connected) {
      try { snapshot.set(await api.get("/api/status")); } catch { /* ignore */ }
    }
  }, 10_000);
}

function openWs() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  try {
    ws = new WebSocket(`${proto}//${location.host}/api/ws`);
  } catch {
    scheduleReconnect();
    return;
  }
  ws.onopen = () => wsConnected.set(true);
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === "status") snapshot.set(msg.data);
    } catch { /* ignore */ }
  };
  ws.onclose = () => {
    wsConnected.set(false);
    ws = null;
    scheduleReconnect();
  };
  ws.onerror = () => ws?.close();
}

function scheduleReconnect() {
  if (wsTimer) return;
  wsTimer = setTimeout(() => {
    wsTimer = null;
    let authed;
    auth.update((a) => (authed = a.authenticated, a));
    if (authed) openWs();
  }, 3000);
}

export function disconnectLive() {
  if (ws) { ws.onclose = null; ws.close(); ws = null; }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  wsConnected.set(false);
}
