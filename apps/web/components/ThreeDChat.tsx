"use client";
import { useState } from "react";
import type { Hotspot, Model3D } from "@/lib/types";
import { Viewer3D } from "./Viewer3D";
import { ChatPanel } from "./ChatPanel";
export function ThreeDChat({model,propertyId}:{model:Model3D;propertyId:string}){const[hotspot,setHotspot]=useState<Hotspot|null>(null);return <div className="detail-content"><div><Viewer3D model={model} propertyId={propertyId} onHotspot={setHotspot}/></div><ChatPanel propertyId={propertyId} hotspot={hotspot}/></div>}
