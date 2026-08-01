"use client";
import { FormEvent, useState } from "react";
import { clientApi } from "@/lib/client-api";
import { formatPrice } from "@/lib/format";
type Result={order:{id:string;status:string;amount:number};payment_intent:{checkout_url:string;provider:string}};
export function ReservationCheckout({propertyId,maxAmount}:{propertyId:string;maxAmount:number}){
  const [result,setResult]=useState<Result|null>(null);const[error,setError]=useState("");
  async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();setError("");const f=new FormData(e.currentTarget);try{const amount=Number(f.get("amount"));const provider=String(f.get("provider"));const data=await clientApi<Result>("/reservations",{method:"POST",body:JSON.stringify({property_id:propertyId,amount,provider,idempotency_key:`web-${propertyId}-${Date.now()}`})});setResult(data)}catch(err){setError(String(err))}}
  return <section className="panel stack"><div><span className="eyebrow">Giữ chỗ P2</span><h2>Thanh toán phí giữ chỗ</h2><p className="muted">Đây là phí giữ chỗ theo chính sách của đơn vị môi giới, không mặc nhiên là tiền đặt cọc chuyển quyền.</p></div><form className="form-grid" onSubmit={(e)=>void submit(e)}><label>Số tiền<input name="amount" type="number" min="100000" max={maxAmount} defaultValue={Math.min(10000000,maxAmount)} required/></label><label>Nhà cung cấp<select name="provider" defaultValue="local"><option value="local">Local sandbox</option><option value="vnpay">VNPAY sandbox</option><option value="stripe">Stripe sandbox</option></select></label><button className="btn btn-primary" type="submit">Tạo giao dịch</button></form>{error&&<p className="error-text">{error}</p>}{result&&<div className="notice"><strong>{formatPrice(result.order.amount)}</strong> · {result.order.status}<br/><a href={result.payment_intent.checkout_url}>Tiếp tục với {result.payment_intent.provider}</a></div>}</section>
}
