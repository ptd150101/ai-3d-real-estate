"use client";

const key = "nestora_analytics_id";
function anonymousId() { let value = localStorage.getItem(key); if (!value) { value = crypto.randomUUID(); localStorage.setItem(key, value); } return value; }
export function track(eventName: string, metadata: Record<string, unknown> = {}, propertyId?: string, agentId?: string) {
  if (typeof window === "undefined") return;
  const body = JSON.stringify({ anonymous_id: anonymousId(), event_name: eventName, metadata_json: metadata, property_id: propertyId, agent_id: agentId, dedupe_key: metadata.dedupeKey as string | undefined, consent: localStorage.getItem("nestora_analytics_consent") === "yes" ? "analytics" : "essential", device_class: window.innerWidth < 700 ? "mobile" : "desktop" });
  const url = "/api/backend/analytics/events";
  if (navigator.sendBeacon) navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
  else fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => undefined);
}
