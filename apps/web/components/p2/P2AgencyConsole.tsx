"use client";
import { FormEvent, useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";

type Json = Record<string, unknown>;
export function P2AgencyConsole({ surface }: { surface: "team" | "finance" | "contracts" | "intelligence" | "reconstruction" | "mlops" }) {
  const [data, setData] = useState<unknown>(null); const [message, setMessage] = useState("");
  useEffect(() => {
    const endpoint = surface === "team" ? "/organizations/members" : surface === "finance" ? "/finance/ledger" : surface === "contracts" ? "/contracts/envelopes" : surface === "mlops" ? "/mlops/dashboard" : "/organizations/current";
    void clientApi(endpoint).then(setData).catch((error) => setMessage(String(error)));
  }, [surface]);
  async function invite(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form=new FormData(event.currentTarget); const result=await clientApi("/organizations/invitations",{method:"POST",body:JSON.stringify({email:form.get("email"),role:form.get("role")})}); setMessage(`Đã tạo lời mời: ${JSON.stringify(result)}`); }
  async function reconcile() { setData(await clientApi("/finance/reconcile",{method:"POST"})); }
  async function createPolicyAndTemplate(event: FormEvent<HTMLFormElement>) { event.preventDefault(); await clientApi("/contracts/policies",{method:"POST",body:JSON.stringify({document_type:"reservation_agreement",jurisdiction:"VN",approved:true})}); const template=await clientApi<Json>("/contracts/templates",{method:"POST",body:JSON.stringify({name:"Thỏa thuận giữ chỗ",document_type:"reservation_agreement",content_html:"Khách hàng {{buyer_name}} giữ chỗ {{property_title}}.",allowed_fields:["buyer_name","property_title"],version:1})}); setMessage(`Đã tạo template ${String(template.id)}`); }
  async function exportTenant() { setData(await clientApi("/organizations/exports",{method:"POST"})); }
  return <section className="container section p2-console"><div className="section-heading"><div><span className="eyebrow">P2 · Agency</span><h1>{({team:"Đội ngũ và phân quyền",finance:"Sổ cái và đối soát",contracts:"Hợp đồng và chữ ký",intelligence:"Định giá và recommendation",reconstruction:"Tái dựng 3D và immersive",mlops:"ML Ops và quản trị chi phí"})[surface]}</h1></div></div>
    {surface === "team" && <div className="split-grid"><form className="panel form-grid" onSubmit={(event)=>void invite(event)}><h3>Mời thành viên</h3><label>Email<input name="email" type="email" required /></label><label>Vai trò<select name="role"><option value="agent">Agent</option><option value="manager">Manager</option><option value="finance">Finance</option><option value="analyst">Analyst</option><option value="reviewer">Reviewer</option></select></label><button className="btn btn-primary">Gửi lời mời</button></form><button className="panel action-card" onClick={()=>void exportTenant()}><strong>Xuất dữ liệu tenant</strong><span>Tạo JSON có checksum và audit trail.</span></button></div>}
    {surface === "finance" && <button className="btn btn-primary" onClick={()=>void reconcile()}>Chạy đối soát</button>}
    {surface === "contracts" && <form className="panel form-grid" onSubmit={(event)=>void createPolicyAndTemplate(event)}><h3>Khởi tạo tài liệu đã duyệt</h3><p>Luồng này tạo legal policy và template Unicode; envelope chỉ được gửi sau khi policy được duyệt.</p><button className="btn btn-primary">Tạo policy + template</button></form>}
    {surface === "intelligence" && <div className="data-grid"><a className="panel action-card" href="/account/valuations"><strong>AVM</strong><span>Prediction interval, comparables, model lineage và human override.</span></a><a className="panel action-card" href="/account/recommendations"><strong>Recommendation</strong><span>Retrieval, ranking, diversity, hide/reset và deterministic fallback.</span></a></div>}
    {surface === "reconstruction" && <div className="panel"><h3>GPU pipeline</h3><p>Capture → quality gate → COLMAP/Nerfstudio adapter → checkpoint → human review → GLB/splat → AR/VR.</p><p>API production: <code>/captures</code>, <code>/reconstruction-jobs</code>, <code>/reconstruction-artifacts</code>.</p></div>}
    {surface === "mlops" && <div className="panel"><h3>Evaluation gate</h3><p>Model chỉ được promote khi có evaluation pass; hỗ trợ canary traffic, rollback và usage/cost records.</p></div>}
    {message && <p className="status-banner">{message}</p>}<pre className="panel code-block">{JSON.stringify(data, null, 2)}</pre></section>;
}
