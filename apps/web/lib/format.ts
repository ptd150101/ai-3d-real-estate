export const formatPrice = (price: number, transaction = "sale") => transaction === "rent" ? `${new Intl.NumberFormat("vi-VN").format(price)} đ/tháng` : price >= 1_000_000_000 ? `${(price / 1_000_000_000).toLocaleString("vi-VN", {maximumFractionDigits: 2})} tỷ` : `${(price / 1_000_000).toLocaleString("vi-VN")} triệu`;

export const absoluteAssetUrl = (url?: string | null) => {
  if (!url) return "/images/property-placeholder.svg";
  if (url.startsWith("http")) return url;
  if (url.startsWith("/models") || url.startsWith("/images") || url.startsWith("/documents")) return url;
  const base = process.env.NEXT_PUBLIC_API_ORIGIN || "http://localhost:8000";
  return `${base}${url}`;
};
