import Image from "next/image";
import Link from "next/link";
import type { PropertySummary } from "@/lib/types";
import { formatPrice } from "@/lib/api";

export function PropertyCard({ property }: { property: PropertySummary }) {
  const image = property.media[0]?.thumbnail_url || property.media[0]?.url || "/images/property-placeholder.svg";
  return <article className="property-card"><Link href={`/properties/${property.slug}`} className="property-media" aria-label={`Xem ${property.title}`}><Image src={image} alt={property.media[0]?.alt_text || property.title} fill sizes="(max-width: 640px) 100vw, (max-width: 980px) 50vw, 33vw" style={{objectFit:"cover"}} /><div className="property-media-top"><span className="badge">{property.transaction_type === "rent" ? "Cho thuê" : "Mua bán"}</span><span className="row-wrap">{property.has_3d && <span className="badge badge-brand">◉ 3D</span>}{property.is_verified && <span className="badge badge-brand">✓ Xác minh</span>}</span></div></Link><div className="property-body"><div className="property-price">{formatPrice(property.price, property.transaction_type)}</div><h3><Link href={`/properties/${property.slug}`}>{property.title}</Link></h3><div className="muted">{property.district}, {property.city}</div><div className="property-meta"><span>{property.area_m2} m²</span><span>{property.bedrooms} PN</span><span>{property.bathrooms} WC</span></div></div></article>;
}
