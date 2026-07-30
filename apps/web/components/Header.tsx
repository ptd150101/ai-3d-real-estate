import Link from "next/link";
import { cookies } from "next/headers";
import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

export async function Header() {
  let user: User | null = null; const token = (await cookies()).get("nestora_token")?.value;
  if (token) { try { user = await apiFetch<User>("/auth/me", { cache: "no-store" }, true); } catch { user = null; } }
  return <header className="header"><div className="container header-inner"><Link href="/" className="brand">NESTORA</Link><nav className="nav" aria-label="Điều hướng chính"><Link href="/properties?transaction_type=sale">Mua nhà</Link><Link href="/properties?transaction_type=rent">Thuê nhà</Link><Link href="/projects/westlake-residence">Dự án</Link><Link href="/agents">Môi giới</Link><Link href="/compare">So sánh</Link></nav><div className="header-actions">{user ? <><Link className="btn btn-secondary btn-sm" href="/favorites">Yêu thích</Link>{(["admin","agent"].includes(user.role)) && <Link className="btn btn-primary btn-sm" href="/admin">Quản trị</Link>}<form action="/api/auth/logout" method="post"><button className="btn btn-ghost btn-sm" type="submit">Đăng xuất</button></form></> : <><Link className="btn btn-secondary btn-sm" href="/login">Đăng nhập</Link><Link className="btn btn-primary btn-sm" href="/register">Tạo tài khoản</Link></>}</div></div></header>;
}
