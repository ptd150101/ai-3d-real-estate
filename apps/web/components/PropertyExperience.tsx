"use client";
import { useState } from "react";
import type { Hotspot, PropertyDetail } from "@/lib/types";
import { Gallery } from "./Gallery";
import { Viewer3D } from "./Viewer3D";

export function PropertyExperience({property,onHotspot}:{property:PropertyDetail;onHotspot?:(h:Hotspot)=>void}){const [viewer,setViewer]=useState(false);return <div>{viewer&&property.model_3d?<div className="stack"><Viewer3D model={property.model_3d} propertyId={property.id} onHotspot={onHotspot}/><button className="btn btn-secondary" onClick={()=>setViewer(false)}>Quay lại thư viện ảnh</button></div>:<Gallery media={property.media} title={property.title} has3D={!!property.model_3d} onOpen3D={()=>setViewer(true)}/>}</div>}
