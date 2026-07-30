import Link from "next/link";
export function Footer() {
  return <footer className="footer"><div className="container footer-grid">
    <div className="stack"><div className="brand">NESTORA</div><p className="muted">Nền tảng bất động sản với dữ liệu xác minh, tư vấn AI theo ngữ cảnh và tour nhà 3D tương tác.</p></div>
    <div className="stack"><strong>Khám phá</strong><Link href="/properties">Tất cả tin</Link><Link href="/properties?has_3d=true">Nhà có 3D</Link><Link href="/compare">So sánh</Link></div>
    <div className="stack"><strong>Hỗ trợ</strong><Link href="/properties">Tìm nhà</Link><Link href="/favorites">Yêu thích</Link><a href="mailto:support@nestora.vn">Liên hệ</a></div>
    <div className="stack"><strong>Thông tin</strong><span className="muted">Hà Nội, Việt Nam</span><span className="muted">support@nestora.vn</span><span className="muted">© 2026 Nestora</span></div>
  </div></footer>;
}
