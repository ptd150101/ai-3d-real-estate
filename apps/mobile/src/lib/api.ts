import Constants from "expo-constants";
import { getDeviceId } from "./device";
import { clearSession, readSession, writeSession } from "./session";
import type { MobileSession } from "./types";

const API_URL = process.env.EXPO_PUBLIC_API_URL || String(Constants.expoConfig?.extra?.apiUrl || "http://localhost:8000/api/v1");
let refreshPromise: Promise<MobileSession | null> | null = null;

async function refresh(): Promise<MobileSession | null> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const session = await readSession();
    if (!session?.refresh_token) return null;
    const response = await fetch(`${API_URL}/mobile/auth/refresh`, { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify({refresh_token: session.refresh_token, device_id: await getDeviceId()}) });
    if (!response.ok) { await clearSession(); return null; }
    const next = await response.json() as MobileSession;
    const merged = {...session, ...next}; await writeSession(merged); return merged;
  })().finally(() => { refreshPromise = null; });
  return refreshPromise;
}

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const session = await readSession();
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: {"content-type":"application/json", ...(session?.access_token ? {authorization:`Bearer ${session.access_token}`} : {}), ...(init.headers || {})} });
  if (response.status === 401 && retry && session?.refresh_token) { const next = await refresh(); if (next) return api<T>(path, init, false); }
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(String((body as {detail?: unknown}).detail || `HTTP ${response.status}`)); }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<MobileSession> {
  const session = await api<MobileSession>("/mobile/auth/login", {method:"POST",body:JSON.stringify({email,password,device_id:await getDeviceId()})}, false);
  await writeSession(session); return session;
}
