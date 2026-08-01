import { cookies } from "next/headers";
import type { PaginatedProperties, PropertyDetail } from "./types";

export const API_URL = process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export async function apiFetch<T>(path: string, init?: RequestInit, withAuth = false): Promise<T> {
  const headers = new Headers(init?.headers); headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (withAuth) {const store = await cookies();const token = store.get("nestora_token")?.value;const organizationId=store.get("nestora_org")?.value;if (token) headers.set("Authorization", `Bearer ${token}`);if(organizationId) headers.set("X-Organization-ID",organizationId);}
  const response = await fetch(`${API_URL}${path}`, { ...init, headers, next: init?.cache === "no-store" ? undefined : { revalidate: 60 } });
  if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getProperties = (query = "") => apiFetch<PaginatedProperties>(`/properties${query ? `?${query}` : ""}`);
export const getProperty = (slug: string) => apiFetch<PropertyDetail>(`/properties/${encodeURIComponent(slug)}`);
export const formatPrice = (price: number, transaction = "sale") => transaction === "rent" ? `${new Intl.NumberFormat("vi-VN").format(price)} đ/tháng` : price >= 1_000_000_000 ? `${(price / 1_000_000_000).toLocaleString("vi-VN", {maximumFractionDigits: 2})} tỷ` : `${(price / 1_000_000).toLocaleString("vi-VN")} triệu`;
export const absoluteAssetUrl = (url?: string | null) => {if (!url) return "/images/property-placeholder.svg";if (url.startsWith("http")) return url;if (url.startsWith("/models") || url.startsWith("/images")) return url;const base = process.env.NEXT_PUBLIC_API_ORIGIN || "http://localhost:8000";return `${base}${url}`;};
