import Constants from "expo-constants";
import { getDeviceId } from "./device";
import { clearSession, readSession, writeSession } from "./session";
import type { MobileSession } from "./types";

const API_URL =
  process.env.EXPO_PUBLIC_API_URL ||
  String(Constants.expoConfig?.extra?.apiUrl || "http://localhost:8000/api/v1");
let refreshPromise: Promise<MobileSession | null> | null = null;

async function refresh(): Promise<MobileSession | null> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const session = await readSession();
    if (!session?.refresh_token) return null;
    const response = await fetch(`${API_URL}/mobile/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        refresh_token: session.refresh_token,
        device_id: await getDeviceId(),
      }),
    });
    if (!response.ok) {
      await clearSession();
      return null;
    }
    const next = (await response.json()) as MobileSession;
    const merged = { ...session, ...next };
    await writeSession(merged);
    return merged;
  })().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

function requestHeaders(init: RequestInit, accessToken?: string): Record<string, string> {
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  return {
    ...(isFormData ? {} : { "content-type": "application/json" }),
    ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
    ...((init.headers || {}) as Record<string, string>),
  };
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const session = await readSession();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: requestHeaders(init, session?.access_token),
  });
  if (response.status === 401 && retry && session?.refresh_token) {
    const next = await refresh();
    if (next) return api<T>(path, init, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(String((body as { detail?: unknown }).detail || `HTTP ${response.status}`));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type MobileUpload = {
  uri: string;
  name: string;
  type: string;
};

export async function upload<T>(
  path: string,
  file: MobileUpload,
  fields: Record<string, string> = {},
  headers: Record<string, string> = {},
): Promise<T> {
  const form = new FormData();
  form.append("file", file as unknown as Blob);
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  return api<T>(path, { method: "POST", body: form, headers });
}

export async function login(email: string, password: string): Promise<MobileSession> {
  const session = await api<MobileSession>(
    "/mobile/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ email, password, device_id: await getDeviceId() }),
    },
    false,
  );
  await writeSession(session);
  return session;
}
