import * as SecureStore from "expo-secure-store";
import type { MobileSession } from "./types";

const KEY = "nestora.mobile-session";
export async function readSession(): Promise<MobileSession | null> {
  const raw = await SecureStore.getItemAsync(KEY);
  if (!raw) return null;
  try { return JSON.parse(raw) as MobileSession; } catch { return null; }
}
export async function writeSession(session: MobileSession): Promise<void> { await SecureStore.setItemAsync(KEY, JSON.stringify(session)); }
export async function clearSession(): Promise<void> { await SecureStore.deleteItemAsync(KEY); }
