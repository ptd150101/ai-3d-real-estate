"use client";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function SearchHero() {
  const [query, setQuery] = useState(""); const router = useRouter();
  async function submit(event: FormEvent) {event.preventDefault();const value = query.trim();if (!value) { router.push("/properties"); return; }try {const response = await fetch("/api/backend/properties/parse-search", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({query:value}) });if (response.ok) {const data = await response.json();const f = data.filters as Record<string, unknown>;const params = new URLSearchParams();if (f.transaction_type) params.set("transaction_type", String(f.transaction_type));if (Array.isArray(f.district)) f.district.forEach((x) => params.append("district", String(x)));if (Array.isArray(f.property_type)) f.property_type.forEach((x) => params.append("property_type", String(x)));["min_price","max_price","min_area","max_area","bedrooms","bathrooms","has_3d","is_owner_listing"].forEach((key) => { if (f[key] !== null && f[key] !== undefined) params.set(key, String(f[key])); });params.set("natural_query", value);router.push(`/properties?${params.toString()}`);return;}} catch {}router.push(`/properties?q=${encodeURIComponent(value)}`);}
  return <form className="search-bar" onSubmit={submit}><input value={query} onChange={(e)=>setQuery(e.target.value)} aria-label="Yêu cầu tìm kiếm" placeholder="Ví dụ: Nhà Cầu Giấy dưới 13 tỷ, ít nhất 3 phòng ngủ, có 3D…" /><button className="btn btn-primary" type="submit">Tìm bất động sản</button></form>;
}
