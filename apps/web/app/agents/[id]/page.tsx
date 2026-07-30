import { notFound } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { PropertyCard } from "@/components/PropertyCard";
import { AgentReviews } from "@/components/p1/AgentReviews";
import { DirectMessageButton } from "@/components/p1/DirectMessageButton";
import type { Agent, PropertySummary } from "@/lib/types";
export default async function Page({params}:{params:Promise<{id:string}>}){const{id}=await params;let data:{agent:Agent;properties:PropertySummary[]};try{data=await apiFetch(`/agents/${id}`)}catch{notFound()}return <section className="section"><div className="container stack"><div className="card card-padded stack"><div className="row-wrap"><h1 style={{fontSize:'3rem'}}>{data.agent.display_name}</h1>{data.agent.verified&&<span className="badge badge-brand">✓ Môi giới xác minh</span>}</div><p>{data.agent.bio}</p><div className="row-wrap"><a className="btn btn-secondary" href={`tel:${data.agent.phone}`}>Gọi {data.agent.phone}</a>{data.agent.email&&<a className="btn btn-secondary" href={`mailto:${data.agent.email}`}>Gửi email</a>}<DirectMessageButton agentId={data.agent.id}/><span className="badge">⭐ {data.agent.rating}</span></div></div><AgentReviews agentId={data.agent.id}/><h2>Tin đang phụ trách</h2><div className="property-grid">{data.properties.map(p=><PropertyCard property={p} key={p.id}/>)}</div></div></section>}
