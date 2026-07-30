"use client";
import { useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";
import { DirectMessageButton } from "./DirectMessageButton";
type Doc={document_id:string;title:string;document_type:string;verified:boolean;version:number;valid_until?:string};
export function LegalDocumentList({propertyId,agentId}:{propertyId:string;agentId?:string}){const[items,setItems]=useState<Doc[]>([]);useEffect(()=>{clientApi<Doc[]>(`/properties/${propertyId}/legal-documents`).then(setItems).catch(()=>setItems([]))},[propertyId]);return <div className="stack">{items.length?<div className="grid grid-3">{items.map(d=><article className="card card-padded stack" key={d.document_id}><strong>{d.title}</strong><div className="row-wrap"><span className="badge badge-brand">✓ Đã duyệt</span><span className="badge">v{d.version}</span></div><p className="muted">Tài liệu được bảo vệ bằng signed access và ghi audit. Liên hệ môi giới để được cấp quyền.</p></article>)}</div>:<div className="empty">Chưa có tài liệu pháp lý đã duyệt.</div>}{agentId&&<DirectMessageButton propertyId={propertyId} agentId={agentId}/>}</div>}
