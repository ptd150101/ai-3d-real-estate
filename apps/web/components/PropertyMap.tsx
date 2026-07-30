"use client";
import { useEffect, useRef } from "react";
import maplibregl, { Map, Marker, Popup } from "maplibre-gl";
import type { PropertySummary } from "@/lib/types";
import { formatPrice } from "@/lib/api";

export function PropertyMap({ properties }: { properties: PropertySummary[] }) {
  const container = useRef<HTMLDivElement>(null); const mapRef = useRef<Map | null>(null);
  useEffect(() => {if (!container.current || mapRef.current) return;const points = properties.filter((p) => p.latitude != null && p.longitude != null);const center: [number, number] = points.length ? [points[0].longitude!, points[0].latitude!] : [105.8342, 21.0278];const map = new maplibregl.Map({container: container.current,center,zoom: 11,style: {version: 8,sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } },layers: [{ id: "osm", type: "raster", source: "osm" }]}});map.addControl(new maplibregl.NavigationControl(), "top-right");const bounds = new maplibregl.LngLatBounds();points.forEach((property) => {const element = document.createElement("button");element.className = "btn btn-primary btn-sm";element.style.padding = "6px 9px";element.textContent = formatPrice(property.price, property.transaction_type);element.setAttribute("aria-label", property.title);const popup = new Popup({ offset: 18 }).setHTML(`<strong>${property.title}</strong><br/><span>${property.district}, ${property.city}</span><br/><a href="/properties/${property.slug}">Xem chi tiết →</a>`);new Marker({ element }).setLngLat([property.longitude!, property.latitude!]).setPopup(popup).addTo(map);bounds.extend([property.longitude!, property.latitude!]);});if (points.length > 1) map.fitBounds(bounds, { padding: 50, maxZoom: 14 });mapRef.current = map;return () => { map.remove(); mapRef.current = null; };}, [properties]);
  return <div ref={container} className="map-box" aria-label="Bản đồ bất động sản" />;
}
