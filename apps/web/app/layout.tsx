import type { Metadata, Viewport } from "next";
import "./globals.css";
import "./dollhouse.css";
import "maplibre-gl/dist/maplibre-gl.css";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: { default: "Nestora — Bất động sản 3D và trợ lý AI", template: "%s | Nestora" },
  description: "Tìm mua và thuê nhà với dữ liệu xác minh, tour 3D tương tác, bản đồ và trợ lý AI theo từng bất động sản.",
  openGraph: { type: "website", locale: "vi_VN", siteName: "Nestora", title: "Nestora — Bất động sản 3D và trợ lý AI", description: "Tìm nhà, xem 3D và hỏi AI." },
  twitter: { card: "summary_large_image" },
  icons: { icon: "/icon.svg" },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#146047" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body><Header/><main>{children}</main><Footer/></body></html>;
}
