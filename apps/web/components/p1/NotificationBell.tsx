"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";

type Notification = { id:string; subject?:string|null; body:string; read_at?:string|null };
export function NotificationBell(){
  const [items,setItems]=useState<Notification[]>([]); const [open,setOpen]=useState(false);
  useEffect(()=>{clientApi<Notification[]>("/notifications?limit=8").then(setItems).catch(()=>setItems([]));},[]);
  const unread=items.filter(x=>!x.read_at).length;
  return <div style={{position:"relative"}}><button className="btn btn-ghost btn-sm" aria-label="Thông báo" onClick={()=>setOpen(!open)}>🔔{unread>0&&<span className="badge badge-brand">{unread}</span>}</button>{open&&<div className="card card-padded stack" style={{position:"absolute",right:0,top:"110%",width:340,zIndex:50,maxHeight:420,overflow:"auto"}}><div className="row" style={{justifyContent:"space-between"}}><strong>Thông báo</strong><Link href="/account/notifications">Xem tất cả</Link></div>{items.length?items.map(item=><button key={item.id} style={{textAlign:"left",border:0,background:item.read_at?"transparent":"var(--brand-soft)",padding:12,borderRadius:10}} onClick={async()=>{await clientApi(`/notifications/${item.id}/read`,{method:"PATCH"});setItems(xs=>xs.map(x=>x.id===item.id?{...x,read_at:new Date().toISOString()}:x));}}><strong>{item.subject||"Cập nhật"}</strong><div className="muted">{item.body}</div></button>):<div className="empty">Chưa có thông báo.</div>}</div>}</div>;
}
