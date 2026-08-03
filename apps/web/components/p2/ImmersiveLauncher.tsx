"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Bounds, Clone, Environment, Html, OrbitControls, useGLTF } from "@react-three/drei";
import { VRButton } from "three/examples/jsm/webxr/VRButton.js";
import { clientApi } from "@/lib/client-api";

type ImmersiveData = {
  ar: null | {
    id: string;
    variants: Record<string, string>;
    placement: Record<string, unknown>;
    scale_meters: number;
  };
  vr: null | {
    id: string;
    navigation: Record<string, unknown>;
    comfort: Record<string, unknown>;
    fallback_url?: string | null;
  };
  web_asset?: string | null;
  fallback: string;
};

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return (
    <Bounds fit clip observe margin={1.15}>
      <Clone object={scene} />
    </Bounds>
  );
}

function WebXRButton({ enabled }: { enabled: boolean }) {
  const { gl } = useThree();
  useEffect(() => {
    if (!enabled || typeof document === "undefined") return;
    gl.xr.enabled = true;
    const button = VRButton.createButton(gl);
    button.dataset.nestoraVrButton = "true";
    document.body.appendChild(button);
    return () => {
      button.remove();
      gl.xr.enabled = false;
    };
  }, [enabled, gl]);
  return null;
}

function ModelViewer({ url, vrEnabled }: { url: string; vrEnabled: boolean }) {
  return (
    <div style={{ height: 440, overflow: "hidden", borderRadius: 18, background: "#eef2f6" }}>
      <Canvas camera={{ position: [3, 2, 4], fov: 45 }} gl={{ antialias: true }}>
        <ambientLight intensity={1.2} />
        <directionalLight position={[4, 6, 3]} intensity={2} />
        <Suspense fallback={<Html center>Đang tải mô hình 3D…</Html>}>
          <Model url={url} />
          <Environment preset="apartment" />
        </Suspense>
        <OrbitControls makeDefault enableDamping />
        <WebXRButton enabled={vrEnabled} />
      </Canvas>
    </div>
  );
}

function androidSceneViewerUrl(assetUrl: string) {
  const absolute = new URL(assetUrl, window.location.origin).toString();
  const query = `file=${encodeURIComponent(absolute)}&mode=ar_preferred&title=Nestora`;
  const fallback = encodeURIComponent(absolute);
  return `intent://arvr.google.com/scene-viewer/1.0?${query}#Intent;scheme=https;package=com.google.ar.core;action=android.intent.action.VIEW;S.browser_fallback_url=${fallback};end;`;
}

export function ImmersiveLauncher({ propertyId }: { propertyId: string }) {
  const [data, setData] = useState<ImmersiveData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vrEnabled, setVrEnabled] = useState(false);

  useEffect(() => {
    let active = true;
    void clientApi(`/properties/${propertyId}/immersive`)
      .then((value) => {
        if (active) setData(value as ImmersiveData);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Không tải được trải nghiệm 3D");
        setData({ ar: null, vr: null, fallback: "gallery_3d" });
      });
    return () => {
      active = false;
    };
  }, [propertyId]);

  const variants = data?.ar?.variants ?? {};
  const webAsset = useMemo(
    () => variants.web || data?.web_asset || data?.vr?.fallback_url || null,
    [data?.vr?.fallback_url, data?.web_asset, variants.web],
  );
  const iosAsset = variants.ios;
  const androidAsset = variants.android || variants.web;
  const isGlb = Boolean(webAsset && /\.glb(?:\?|$)/i.test(webAsset));

  if (!data) return <div className="panel">Đang kiểm tra AR/VR…</div>;

  return (
    <section className="panel" aria-labelledby="immersive-heading">
      <h2 id="immersive-heading">Trải nghiệm không gian</h2>
      <p>
        Xoay, thu phóng mô hình trực tiếp trên web; thiết bị tương thích có thể mở AR Quick Look,
        Scene Viewer hoặc WebXR.
      </p>

      {isGlb && webAsset ? (
        <ModelViewer url={webAsset} vrEnabled={vrEnabled} />
      ) : webAsset ? (
        <p>
          Asset này dùng định dạng chuyên dụng. <a href={webAsset} target="_blank" rel="noreferrer">Mở trình xem</a>
        </p>
      ) : (
        <p className="muted">Chưa có asset đã duyệt; sử dụng gallery hiện tại.</p>
      )}

      <div className="button-row" style={{ marginTop: 16 }}>
        {iosAsset ? (
          <a className="btn btn-primary" href={iosAsset} rel="ar">
            <img
              alt=""
              aria-hidden="true"
              width={1}
              height={1}
              src="data:image/gif;base64,R0lGODlhAQABAAAAACw="
            />
            <span>Mở AR trên iPhone/iPad</span>
          </a>
        ) : null}
        {androidAsset ? (
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              window.location.href = androidSceneViewerUrl(androidAsset);
            }}
          >
            Mở AR trên Android
          </button>
        ) : null}
        <button
          className="btn btn-secondary"
          type="button"
          disabled={!isGlb || !data.vr}
          onClick={() => setVrEnabled((value) => !value)}
        >
          {vrEnabled ? "Tắt WebXR" : "Bật WebXR"}
        </button>
        {webAsset ? (
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => document.documentElement.requestFullscreen?.()}
          >
            Toàn màn hình
          </button>
        ) : null}
      </div>
      {vrEnabled ? (
        <p className="muted">Nút “Enter VR” xuất hiện ở cuối màn hình khi trình duyệt hỗ trợ WebXR.</p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
