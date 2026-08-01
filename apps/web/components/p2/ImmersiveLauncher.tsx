"use client";
import { useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";
export function ImmersiveLauncher({ propertyId }: { propertyId: string }) {
  const [data,setData]=useState<any>(null);
  useEffect(()=>{void clientApi(`/properties/${propertyId}/immersive`).then(setData).catch(()=>setData({fallback:"gallery_3d"}));},[propertyId]);
  if(!data)return <div className="panel">Đang kiểm tra AR/VR…</div>;
  return <div className="panel"><h2>Trải nghiệm không gian</h2><p>Hệ thống tự phát hiện khả năng thiết bị và luôn giữ gallery/3D làm fallback.</p><div className="button-row"><button className="btn btn-primary" disabled={!data.ar} onClick={()=>data.ar&&alert(`AR variants: ${JSON.stringify(data.ar.variants)}`)}>Mở AR</button><button className="btn btn-secondary" disabled={!data.vr} onClick={()=>data.vr&&alert(`VR comfort: ${JSON.stringify(data.vr.comfort)}`)}>Mở VR</button></div>{!data.ar&&!data.vr&&<p className="muted">Chưa có asset đã duyệt; sử dụng tour 3D hiện tại.</p>}</div>;
}
