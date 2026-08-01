"use client";
import { FormEvent, useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";
import { formatPrice } from "@/lib/format";

type Recommendation = { property_id: string; slug: string; title: string; price: number; district: string; score: number; reason: string };
type Reservation = { id: string; property_id: string; status: string; amount: number; currency: string; expires_at: string };

export function P2BuyerConsole({ surface }: { surface: "payments" | "recommendations" | "valuations" }) {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [valuation, setValuation] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (surface === "recommendations") void clientApi<{items: Recommendation[]}>("/recommendations").then((x) => setRecommendations(x.items)).catch((error) => setMessage(String(error)));
    if (surface === "payments") void clientApi<Reservation[]>("/reservations/me").then(setReservations).catch((error) => setMessage(String(error)));
  }, [surface]);
  async function submitValuation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const result = await clientApi<Record<string, unknown>>("/valuations", { method: "POST", body: JSON.stringify({ district: form.get("district"), property_type: form.get("property_type"), area_m2: Number(form.get("area_m2")), bedrooms: Number(form.get("bedrooms")), legal_status: form.get("legal_status") }) }); setValuation(result);
  }
  async function hide(propertyId: string) { await clientApi("/recommendations/feedback", { method: "POST", body: JSON.stringify({ property_id: propertyId, action: "hide" }) }); setRecommendations((items) => items.filter((item) => item.property_id !== propertyId)); }
  return <section className="container section p2-console">
    {surface === "payments" && <><div className="section-heading"><div><span className="eyebrow">P2 · Giao dịch</span><h1>Lịch sử giữ chỗ và thanh toán</h1></div></div><div className="data-grid">{reservations.length ? reservations.map((item) => <article className="panel" key={item.id}><strong>{formatPrice(item.amount)}</strong><p>Trạng thái: {item.status}</p><p>Hết hạn: {new Date(item.expires_at).toLocaleString("vi-VN")}</p><a className="btn btn-secondary btn-sm" href={`/api/backend/reservations/${item.id}/receipt`} target="_blank">Tải biên nhận</a></article>) : <div className="empty-state">Bạn chưa có giao dịch giữ chỗ.</div>}</div></>}
    {surface === "recommendations" && <><div className="section-heading"><div><span className="eyebrow">P2 · Cá nhân hóa</span><h1>Bất động sản dành cho bạn</h1></div></div><div className="data-grid">{recommendations.map((item) => <article className="panel" key={item.property_id}><span className="badge">Điểm {item.score.toFixed(2)}</span><h3><a href={`/properties/${item.slug}`}>{item.title}</a></h3><strong>{formatPrice(item.price)}</strong><p>{item.district} · {item.reason}</p><button className="btn btn-ghost btn-sm" onClick={() => void hide(item.property_id)}>Không phù hợp</button></article>)}</div></>}
    {surface === "valuations" && <><div className="section-heading"><div><span className="eyebrow">P2 · AVM</span><h1>Ước tính giá có khoảng tin cậy</h1></div></div><form className="panel form-grid" onSubmit={(event) => void submitValuation(event)}><label>Quận<input name="district" defaultValue="Tây Hồ" required /></label><label>Loại hình<select name="property_type" defaultValue="apartment"><option value="apartment">Căn hộ</option><option value="townhouse">Nhà phố</option><option value="villa">Biệt thự</option></select></label><label>Diện tích<input name="area_m2" type="number" defaultValue="100" min="1" required /></label><label>Phòng ngủ<input name="bedrooms" type="number" defaultValue="3" min="0" /></label><label>Pháp lý<input name="legal_status" defaultValue="Sổ đỏ lâu dài" /></label><button className="btn btn-primary" type="submit">Định giá</button></form>{valuation && <pre className="panel code-block">{JSON.stringify(valuation, null, 2)}</pre>}</>}
    {message && <p className="error-banner">{message}</p>}
  </section>;
}
