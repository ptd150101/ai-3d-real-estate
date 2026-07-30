import type { Metadata } from "next";
import { PropertyCard } from "@/components/PropertyCard";
import { PropertyMap } from "@/components/PropertyMap";
import { SearchFilters } from "@/components/SearchFilters";
import { SaveSearchButton } from "@/components/SaveSearchButton";
import { getProperties } from "@/lib/api";

export const metadata: Metadata = { title: "Tìm bất động sản", description: "Tìm mua và thuê nhà theo vị trí, giá, diện tích, tiện ích và trải nghiệm 3D." };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
export default async function PropertiesPage({ searchParams }: { searchParams: SearchParams }) {
  const raw = await searchParams; const query = new URLSearchParams();
  Object.entries(raw).forEach(([key,value]) => {if (key === "natural_query" || value == null || value === "") return;if (Array.isArray(value)) value.forEach((v)=>query.append(key,v)); else query.append(key,value);});
  if (!query.has("page_size")) query.set("page_size","18");
  const data = await getProperties(query.toString()); const districts = (data.facets.districts || []).map((x)=>x.value); const view = typeof raw.view === "string" ? raw.view : "grid";
  return <section className="section-tight"><div className="container stack" style={{gap:24}}>
    <div className="stack" style={{gap:8}}><span className="eyebrow">Marketplace</span><h1 style={{fontSize:"clamp(2rem,4vw,3.5rem)"}}>Tìm bất động sản</h1>{raw.natural_query && <p className="muted">Yêu cầu: “{String(raw.natural_query)}”</p>}</div>
    <div className="search-layout"><SearchFilters districts={districts}/><div><div className="search-toolbar"><div className="row-wrap"><div><strong>{data.total}</strong> kết quả</div><SaveSearchButton/></div><div className="row-wrap"><a className={`btn btn-sm ${view === "grid" ? "btn-primary":"btn-secondary"}`} href={`?${new URLSearchParams({...Object.fromEntries(query),view:"grid"})}`}>Dạng lưới</a><a className={`btn btn-sm ${view === "map" ? "btn-primary":"btn-secondary"}`} href={`?${new URLSearchParams({...Object.fromEntries(query),view:"map"})}`}>Bản đồ</a><form method="get">{Array.from(query.entries()).filter(([k])=>k!=="sort").map(([k,v],i)=><input key={`${k}-${i}`} type="hidden" name={k} value={v}/>)}<select className="select" name="sort" defaultValue={query.get("sort") || "newest"}><option value="newest">Mới nhất</option><option value="price_asc">Giá thấp đến cao</option><option value="price_desc">Giá cao đến thấp</option><option value="area_desc">Diện tích lớn</option></select><button className="btn btn-secondary btn-sm" type="submit">Sắp xếp</button></form></div></div>
      {data.items.length === 0 ? <div className="empty"><h3>Chưa tìm thấy căn phù hợp</h3><p>Hãy thử nới khoảng giá hoặc chọn khu vực khác.</p></div> : view === "map" ? <div className="map-layout"><div className="property-grid" style={{gridTemplateColumns:"1fr"}}>{data.items.map((p)=><PropertyCard property={p} key={p.id}/>)}</div><PropertyMap properties={data.items}/></div> : <div className="property-grid">{data.items.map((p)=><PropertyCard property={p} key={p.id}/>)}</div>}
      {data.pages > 1 && <div className="row-wrap" style={{justifyContent:"center",marginTop:28}}>{Array.from({length:data.pages},(_,i)=>i+1).map((page)=><a key={page} className={`btn btn-sm ${page===data.page?"btn-primary":"btn-secondary"}`} href={`?${new URLSearchParams({...Object.fromEntries(query),page:String(page)})}`}>{page}</a>)}</div>}
    </div></div>
  </div></section>;
}
