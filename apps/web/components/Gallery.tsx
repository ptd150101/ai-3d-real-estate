"use client";
import Image from "next/image";
import { useState } from "react";
import type { Media } from "@/lib/types";

export function Gallery({ media, title, onOpen3D, has3D }: { media: Media[]; title: string; onOpen3D?: () => void; has3D?: boolean }) {
  const items = media.length ? media : [{id:"placeholder",media_type:"image",url:"/images/property-placeholder.svg",sort_order:0}];
  const [active, setActive] = useState(0); const item = items[active] || items[0];
  return <div><div className="gallery-main"><Image src={item.url} alt={item.alt_text || title} fill priority sizes="(max-width:980px) 100vw, 65vw" style={{objectFit:"cover"}}/>{has3D && <button type="button" className="btn btn-primary" style={{position:"absolute",left:18,bottom:18}} onClick={onOpen3D}>◉ Xem mô hình 3D</button>}</div><div className="gallery-thumbs">{items.slice(0,8).map((x,index)=><button type="button" key={x.id} className={`gallery-thumb ${index===active?"active":""}`} onClick={()=>setActive(index)}><Image src={x.thumbnail_url || x.url} alt={x.alt_text || `${title} ${index+1}`} width={240} height={180} style={{width:"100%",height:"100%",objectFit:"cover"}}/></button>)}</div></div>;
}
