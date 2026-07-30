import Link from "next/link";
import { SearchHero } from "@/components/SearchHero";
import { PropertyCard } from "@/components/PropertyCard";
import { getProperties } from "@/lib/api";

export default async function HomePage() {
  const data = await getProperties("page_size=6&sort=newest");
  const threeDCount = data.items.filter((x)=>x.has_3d).length;
  return <>
    <section className="hero"><div className="container hero-panel"><div className="hero-copy">
      <span className="eyebrow" style={{color:"#cce9dc"}}>Real estate, reimagined</span>
      <h1>Tìm ngôi nhà phù hợp với cách bạn sống</h1>
      <p>Khám phá dữ liệu đã xác minh, xem căn nhà bằng mô hình 3D và hỏi trợ lý AI ngay trong từng tin đăng.</p>
      <SearchHero />
      <div className="row-wrap"><span className="badge badge-brand">✓ Tin được kiểm duyệt</span><span className="badge badge-brand">◉ {threeDCount}+ căn mẫu có 3D</span><span className="badge badge-brand">AI theo ngữ cảnh</span></div>
    </div></div></section>
    <section className="section"><div className="container stack" style={{gap:28}}>
      <div className="row" style={{justifyContent:"space-between",alignItems:"end"}}><div className="stack" style={{gap:8}}><span className="eyebrow">Gợi ý hôm nay</span><h2>Bất động sản nổi bật</h2></div><Link className="btn btn-secondary" href="/properties">Xem tất cả</Link></div>
      <div className="property-grid">{data.items.map((property)=><PropertyCard key={property.id} property={property}/>)}</div>
    </div></section>
    <section className="section-tight"><div className="container feature-panel">
      <div className="stack" style={{gap:18}}><span className="eyebrow">Trải nghiệm khác biệt</span><h2>Xem nhà bằng 3D. Hỏi mọi thứ bằng AI.</h2><p className="muted">Viewer cho phép chuyển tầng, bật/tắt nội thất, chọn hotspot từng phòng và đi bộ trong mô hình. Chatbot tự nhận căn nhà, tầng và phòng bạn đang xem.</p><div className="row-wrap"><Link className="btn btn-primary" href="/properties?has_3d=true">Khám phá nhà có 3D</Link><Link className="btn btn-secondary" href="/properties/nha-pho-hien-dai-cau-giay">Xem bản demo</Link></div></div>
      <div className="feature-visual"><div className="stack"><div style={{fontSize:"4rem"}}>⌂</div><h3>Three.js Property Tour</h3><p style={{color:"rgba(255,255,255,.7)"}}>Orbit · Floor · Furniture · Hotspot · Walk · Quality scaling</p></div></div>
    </div></section>
    <section className="section"><div className="container grid grid-3">
      {[['Tìm kiếm tự nhiên','Nhập yêu cầu bằng tiếng Việt; hệ thống chuyển thành bộ lọc có cấu trúc.'],['Dữ liệu có nguồn','Pháp lý và chính sách chỉ được trả lời từ tài liệu đã đánh dấu xác minh.'],['Đặt lịch tức thì','Chọn thời gian xem nhà, theo dõi trạng thái và chuyển sang tư vấn viên khi cần.']].map(([title,body])=><div className="card card-padded stack" key={title}><span className="badge badge-brand">Nestora</span><h3>{title}</h3><p className="muted">{body}</p></div>)}
    </div></section>
  </>;
}
