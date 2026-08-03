"use client";

import { FormEvent, useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";
import { formatPrice } from "@/lib/format";

type Recommendation = {
  property_id: string;
  slug: string;
  title: string;
  price: number;
  district: string;
  score: number;
  reason: string;
  source?: string;
  model?: string | null;
};
type Reservation = {
  id: string;
  property_id: string;
  status: string;
  amount: number;
  currency: string;
  expires_at: string;
};
type Comparable = {
  property_id?: string;
  title?: string;
  price?: number;
  similarity?: number;
  adjustments?: Record<string, unknown>;
};
type Valuation = {
  id?: string;
  status: string;
  estimate?: number | null;
  confidence?: number;
  range?: { lower?: number | null; upper?: number | null };
  explanation?: Record<string, unknown>;
  comparables?: Comparable[];
  model?: Record<string, unknown> | null;
};

export function P2BuyerConsole({
  surface,
}: {
  surface: "payments" | "recommendations" | "valuations";
}) {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [valuation, setValuation] = useState<Valuation | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (surface === "recommendations") {
      void clientApi<{ items: Recommendation[] }>("/recommendations")
        .then((response) => setRecommendations(response.items))
        .catch((error) => setMessage(String(error)));
    }
    if (surface === "payments") {
      void clientApi<Reservation[]>("/reservations/me")
        .then(setReservations)
        .catch((error) => setMessage(String(error)));
    }
  }, [surface]);

  async function submitValuation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true);
    setMessage("");
    try {
      const result = await clientApi<Valuation>("/valuations", {
        method: "POST",
        body: JSON.stringify({
          district: form.get("district"),
          property_type: form.get("property_type"),
          area_m2: Number(form.get("area_m2")),
          bedrooms: Number(form.get("bedrooms")),
          legal_status: form.get("legal_status"),
        }),
      });
      setValuation(result);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setLoading(false);
    }
  }

  async function hide(propertyId: string) {
    await clientApi("/recommendations/feedback", {
      method: "POST",
      body: JSON.stringify({ property_id: propertyId, action: "hide" }),
    });
    setRecommendations((items) => items.filter((item) => item.property_id !== propertyId));
  }

  async function resetRecommendations() {
    await clientApi("/recommendations/profile", {
      method: "PATCH",
      body: JSON.stringify({ reset: true, enabled: true }),
    });
    const response = await clientApi<{ items: Recommendation[] }>("/recommendations");
    setRecommendations(response.items);
  }

  return (
    <section className="container section p2-console">
      {surface === "payments" ? <Payments reservations={reservations} /> : null}
      {surface === "recommendations" ? (
        <Recommendations
          recommendations={recommendations}
          onHide={(id) => void hide(id)}
          onReset={() => void resetRecommendations()}
        />
      ) : null}
      {surface === "valuations" ? (
        <Valuations valuation={valuation} loading={loading} onSubmit={submitValuation} />
      ) : null}
      {message ? <p className="error-banner">{message}</p> : null}
    </section>
  );
}

function Payments({ reservations }: { reservations: Reservation[] }) {
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">P2 · Giao dịch</span>
          <h1>Lịch sử giữ chỗ và thanh toán</h1>
        </div>
      </div>
      <div className="data-grid">
        {reservations.length ? (
          reservations.map((item) => (
            <article className="panel" key={item.id}>
              <span className="badge">{item.status}</span>
              <h3>{formatPrice(item.amount)}</h3>
              <p>Hết hạn: {new Date(item.expires_at).toLocaleString("vi-VN")}</p>
              <a
                className="btn btn-secondary btn-sm"
                href={`/api/backend/reservations/${item.id}/receipt`}
                target="_blank"
              >
                Tải biên nhận
              </a>
            </article>
          ))
        ) : (
          <div className="empty-state">Bạn chưa có giao dịch giữ chỗ.</div>
        )}
      </div>
    </>
  );
}

function Recommendations({
  recommendations,
  onHide,
  onReset,
}: {
  recommendations: Recommendation[];
  onHide: (id: string) => void;
  onReset: () => void;
}) {
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">P2 · Cá nhân hóa</span>
          <h1>Bất động sản dành cho bạn</h1>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onReset}>Đặt lại tín hiệu</button>
      </div>
      <div className="data-grid">
        {recommendations.map((item) => (
          <article className="panel" key={item.property_id}>
            <span className="badge">Điểm {(item.score * 100).toFixed(0)}%</span>
            <h3><a href={`/properties/${item.slug}`}>{item.title}</a></h3>
            <strong>{formatPrice(item.price)}</strong>
            <p>{item.district} · {item.reason}</p>
            <small>{item.source === "model" ? `Model ${item.model || "production"}` : "Fallback xác định"}</small>
            <div className="button-row">
              <a className="btn btn-secondary btn-sm" href={`/properties/${item.slug}`}>Xem tin</a>
              <button className="btn btn-ghost btn-sm" onClick={() => onHide(item.property_id)}>Không phù hợp</button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function Valuations({
  valuation,
  loading,
  onSubmit,
}: {
  valuation: Valuation | null;
  loading: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const explanation = valuation?.explanation || {};
  const comparables = valuation?.comparables || [];
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">P2 · AVM</span>
          <h1>Ước tính giá có khoảng tin cậy</h1>
        </div>
      </div>
      <form className="panel form-grid" onSubmit={(event) => void onSubmit(event)}>
        <label>Quận<input name="district" defaultValue="Tây Hồ" required /></label>
        <label>
          Loại hình
          <select name="property_type" defaultValue="apartment">
            <option value="apartment">Căn hộ</option>
            <option value="townhouse">Nhà phố</option>
            <option value="villa">Biệt thự</option>
            <option value="land">Đất</option>
          </select>
        </label>
        <label>Diện tích<input name="area_m2" type="number" defaultValue="100" min="1" required /></label>
        <label>Phòng ngủ<input name="bedrooms" type="number" defaultValue="3" min="0" /></label>
        <label>Pháp lý<input name="legal_status" defaultValue="Sổ đỏ lâu dài" /></label>
        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading ? "Đang định giá…" : "Định giá"}
        </button>
      </form>

      {valuation ? (
        <>
          <div className="split-grid">
            <article className="panel">
              <span className="eyebrow">Ước tính trung tâm</span>
              <h2>{valuation.estimate ? formatPrice(valuation.estimate) : "Không đủ dữ liệu"}</h2>
              <p>Độ tin cậy {Math.round(Number(valuation.confidence || 0) * 100)}%</p>
            </article>
            <article className="panel">
              <span className="eyebrow">Khoảng dự báo</span>
              <h3>
                {valuation.range?.lower ? formatPrice(valuation.range.lower) : "—"}
                {" – "}
                {valuation.range?.upper ? formatPrice(valuation.range.upper) : "—"}
              </h3>
              <p>{String(explanation.caveat || "Kết quả chỉ mang tính tham khảo.")}</p>
            </article>
          </div>
          <div className="panel">
            <h3>Giải thích</h3>
            <dl className="detail-list">
              <div><dt>Nguồn</dt><dd>{String(explanation.runtime || "baseline")}</dd></div>
              <div><dt>Số tài sản so sánh</dt><dd>{String(explanation.comparable_count || comparables.length)}</dd></div>
              {explanation.price_per_m2 ? <div><dt>Giá tham chiếu/m²</dt><dd>{formatPrice(explanation.price_per_m2)}</dd></div> : null}
            </dl>
          </div>
          {comparables.length ? (
            <div className="data-grid">
              {comparables.map((item, index) => (
                <article className="panel" key={item.property_id || index}>
                  <strong>{item.title || `Tài sản so sánh ${index + 1}`}</strong>
                  {item.price ? <p>{formatPrice(item.price)}</p> : null}
                  <p>Độ tương đồng {Math.round(Number(item.similarity || 0) * 100)}%</p>
                </article>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}
