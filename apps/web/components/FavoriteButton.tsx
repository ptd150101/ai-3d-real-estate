"use client";
import { useState } from "react";

export function FavoriteButton({ propertyId }: { propertyId: string }) {
  const [saved,setSaved] = useState(false); const [busy,setBusy]=useState(false);
  async function toggle(){ setBusy(true); const response=await fetch(`/api/backend/favorites/${propertyId}`,{method:saved?"DELETE":"PUT"}); if(response.status===401){location.href="/login";return;} if(response.ok)setSaved(!saved); setBusy(false); }
  return <button className="btn btn-secondary" type="button" onClick={toggle} disabled={busy}>{saved?"♥ Đã lưu":"♡ Yêu thích"}</button>;
}
