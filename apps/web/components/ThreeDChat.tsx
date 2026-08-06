"use client";

import { useState } from "react";
import type { Hotspot, Model3D } from "@/lib/types";
import { Viewer3D } from "./Viewer3D";
import { ChatPanel } from "./ChatPanel";

export function ThreeDChat({ model, propertyId }: { model: Model3D; propertyId: string }) {
  const [hotspot, setHotspot] = useState<Hotspot | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  return (
    <div className="three-d-experience">
      <Viewer3D
        model={model}
        propertyId={propertyId}
        onHotspot={(selected) => {
          setHotspot(selected);
          setChatOpen(true);
        }}
      />
      <div className="viewer-chat-drawer">
        <button
          type="button"
          className="btn btn-secondary viewer-chat-toggle"
          onClick={() => setChatOpen((value) => !value)}
          aria-expanded={chatOpen}
        >
          {chatOpen ? "Đóng trợ lý AI" : "Hỏi AI về mô hình và từng phòng"}
        </button>
        {chatOpen && <ChatPanel propertyId={propertyId} hotspot={hotspot} />}
      </div>
    </div>
  );
}
