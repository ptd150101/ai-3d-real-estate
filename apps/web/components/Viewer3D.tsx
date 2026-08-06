"use client";

import React, {
  Component,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  Bounds,
  ContactShadows,
  Environment,
  Html,
  OrbitControls,
  PointerLockControls,
  useGLTF,
} from "@react-three/drei";
import * as THREE from "three";
import type { Hotspot, Model3D } from "@/lib/types";
import { clientApi } from "@/lib/client-api";
import { track } from "@/lib/analytics";

type Zone = {
  id: string;
  floor_id?: string | null;
  name: string;
  zone_type: string;
  points_json: number[][];
  min_y: number;
  max_y: number;
};

type ViewMode = "dollhouse" | "orbit" | "walk";
type Vector3Tuple = [number, number, number];

function vector3(value: number[] | undefined, fallback: Vector3Tuple): Vector3Tuple {
  if (!value || value.length < 3) return fallback;
  return [Number(value[0]), Number(value[1]), Number(value[2])];
}

class ViewerErrorBoundary extends Component<
  { children: React.ReactNode; poster?: string | null },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div
        className="viewer-poster"
        style={{
          backgroundImage: `url(${this.props.poster || "/images/property-placeholder.svg"})`,
        }}
      >
        <div className="stack viewer-empty-state">
          <h3>Không thể tải mô hình 3D</h3>
          <p>Thiết bị hoặc trình duyệt hiện tại không hỗ trợ. Bạn vẫn có thể xem thư viện ảnh.</p>
        </div>
      </div>
    );
  }
}

function inside(point: [number, number], polygon: number[][]) {
  let result = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, zi] = polygon[i];
    const [xj, zj] = polygon[j];
    const intersect =
      (zi > point[1]) !== (zj > point[1]) &&
      point[0] < ((xj - xi) * (point[1] - zi)) / (zj - zi || 1e-9) + xi;
    if (intersect) result = !result;
  }
  return result;
}

function nearest(point: [number, number], zones: Zone[]) {
  let best: [number, number] = point;
  let distance = Infinity;
  for (const zone of zones) {
    for (const candidate of zone.points_json) {
      const current = (candidate[0] - point[0]) ** 2 + (candidate[1] - point[1]) ** 2;
      if (current < distance) {
        distance = current;
        best = [candidate[0], candidate[1]];
      }
    }
  }
  return best;
}

function WalkController({
  enabled,
  zones,
  onPosition,
}: {
  enabled: boolean;
  zones: Zone[];
  onPosition: (position: [number, number]) => void;
}) {
  const { camera } = useThree();
  const keys = useRef(new Set<string>());

  useEffect(() => {
    const down = (event: KeyboardEvent) => keys.current.add(event.code);
    const up = (event: KeyboardEvent) => keys.current.delete(event.code);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  useFrame((_, delta) => {
    if (!enabled) return;
    const forward = new THREE.Vector3();
    camera.getWorldDirection(forward);
    forward.y = 0;
    forward.normalize();
    const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize();
    const velocity = new THREE.Vector3();
    if (keys.current.has("KeyW")) velocity.add(forward);
    if (keys.current.has("KeyS")) velocity.sub(forward);
    if (keys.current.has("KeyD")) velocity.add(right);
    if (keys.current.has("KeyA")) velocity.sub(right);
    if (velocity.lengthSq() === 0) return;

    velocity.normalize().multiplyScalar(delta * 3);
    const next = camera.position.clone().add(velocity);
    const available = zones.filter((zone) => next.y >= zone.min_y && next.y <= zone.max_y);
    if (!available.length || available.some((zone) => inside([next.x, next.z], zone.points_json))) {
      camera.position.copy(next);
    } else {
      const point = nearest([next.x, next.z], available);
      camera.position.x = point[0];
      camera.position.z = point[1];
    }
    camera.position.y = THREE.MathUtils.clamp(camera.position.y, 1.4, 12);
    onPosition([camera.position.x, camera.position.z]);
  });

  return enabled ? <PointerLockControls /> : null;
}

function floorIndexForName(model: Model3D, objectName: string): number {
  return model.floors.findIndex((floor) =>
    [...floor.object_names, ...floor.furniture_object_names].some(
      (name) => objectName === name || objectName.startsWith(name),
    ),
  );
}

function SceneModel({
  model,
  activeFloor,
  showFurniture,
  showRoof,
  explodeFloors,
  onHotspot,
}: {
  model: Model3D;
  activeFloor: string;
  showFurniture: boolean;
  showRoof: boolean;
  explodeFloors: boolean;
  onHotspot: (hotspot: Hotspot) => void;
}) {
  const gltf = useGLTF(model.model_url);
  const scene = useMemo(() => gltf.scene.clone(true), [gltf.scene]);

  useEffect(() => {
    const active = model.floors.find((floor) => floor.id === activeFloor);
    const allowed = active ? [...active.object_names, ...active.furniture_object_names] : [];
    const furnitureNames = model.floors.flatMap((floor) => floor.furniture_object_names);
    const allFloorNames = model.floors.flatMap((floor) => [
      ...floor.object_names,
      ...floor.furniture_object_names,
    ]);

    scene.traverse((object) => {
      if (!object.name) return;
      if (!object.userData.nestoraBasePosition) {
        object.userData.nestoraBasePosition = object.position.toArray();
      }
      const base = object.userData.nestoraBasePosition as number[];
      const floorIndex = floorIndexForName(model, object.name);
      const floorOwned = allFloorNames.some(
        (name) => object.name === name || object.name.startsWith(name),
      );
      const floorVisible =
        activeFloor === "all" ||
        !floorOwned ||
        allowed.some((name) => object.name === name || object.name.startsWith(name));
      const isFurniture = furnitureNames.some(
        (name) => object.name === name || object.name.startsWith(name),
      );
      const isRoof = object.name.startsWith("Roof");
      object.visible = floorVisible && (!isFurniture || showFurniture) && (!isRoof || showRoof);
      object.position.set(
        Number(base[0] || 0),
        Number(base[1] || 0) + (explodeFloors && floorIndex >= 0 ? floorIndex * 0.9 : 0),
        Number(base[2] || 0),
      );
      if ((object as THREE.Mesh).isMesh) {
        const mesh = object as THREE.Mesh;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
      }
    });
  }, [scene, model, activeFloor, showFurniture, showRoof, explodeFloors]);

  const hotspots = model.hotspots.filter(
    (hotspot) => activeFloor === "all" || !hotspot.floor_id || hotspot.floor_id === activeFloor,
  );

  return (
    <group>
      <primitive object={scene} />
      {hotspots.map((hotspot) => (
        <Html
          key={hotspot.id}
          position={hotspot.position as Vector3Tuple}
          center
          distanceFactor={8}
          zIndexRange={[30, 0]}
        >
          <button
            className="hotspot"
            type="button"
            title={hotspot.label}
            aria-label={`Mở thông tin ${hotspot.label}`}
            onClick={() => onHotspot(hotspot)}
          >
            i
          </button>
        </Html>
      ))}
    </group>
  );
}

function CameraFocus({ hotspot }: { hotspot: Hotspot | null }) {
  const { camera } = useThree();
  useEffect(() => {
    if (!hotspot?.camera_position) return;
    const position = vector3(hotspot.camera_position, [8, 6, 8]);
    const target = vector3(hotspot.position, [0, 1, 0]);
    camera.position.set(...position);
    camera.lookAt(...target);
    camera.updateProjectionMatrix();
  }, [camera, hotspot]);
  return null;
}

function MiniMap({ zones, position }: { zones: Zone[]; position: [number, number] }) {
  const points = zones.flatMap((zone) => zone.points_json);
  if (!points.length) return null;
  const xs = points.map((point) => point[0]);
  const zs = points.map((point) => point[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  const sx = (x: number) => 10 + ((x - minX) / (maxX - minX || 1)) * 160;
  const sz = (z: number) => 10 + ((z - minZ) / (maxZ - minZ || 1)) * 110;
  return (
    <svg className="viewer-minimap" width="180" height="130" viewBox="0 0 180 130">
      {zones.map((zone) => (
        <polygon
          key={zone.id}
          points={zone.points_json.map((point) => `${sx(point[0])},${sz(point[1])}`).join(" ")}
          fill="rgba(20,96,71,.18)"
          stroke="#146047"
          strokeWidth="2"
        />
      ))}
      <circle cx={sx(position[0])} cy={sz(position[1])} r="5" fill="#e84b4b" />
    </svg>
  );
}

export function Viewer3D({
  model,
  propertyId,
  onHotspot,
}: {
  model: Model3D;
  propertyId: string;
  onHotspot?: (hotspot: Hotspot) => void;
}) {
  const [started, setStarted] = useState(false);
  const [floor, setFloor] = useState("all");
  const [showFurniture, setShowFurniture] = useState(true);
  const [showRoof, setShowRoof] = useState(false);
  const [explodeFloors, setExplodeFloors] = useState(model.floors.length > 1);
  const [viewMode, setViewMode] = useState<ViewMode>("dollhouse");
  const [quality, setQuality] = useState<"low" | "medium" | "high">("medium");
  const [reset, setReset] = useState(0);
  const [selected, setSelected] = useState<Hotspot | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [position, setPosition] = useState<[number, number]>([0, 0]);
  const shell = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    clientApi<{ navigation_zones?: Zone[] }>(`/properties/${propertyId}/panorama`)
      .then((result) => {
        if (active) setZones(result.navigation_zones || []);
      })
      .catch(() => {
        if (active) setZones([]);
      });
    return () => {
      active = false;
    };
  }, [propertyId]);

  const defaultPosition = vector3(model.default_camera?.position, [10, 8, 10]);
  const defaultTarget = vector3(model.default_camera?.target, [0, 1, 0]);
  const cameraZoom = Number(model.default_camera?.zoom || 48);
  const dpr: number | [number, number] =
    quality === "low" ? 1 : quality === "high" ? [1.5, 2] : [1, 1.5];
  const activeZones = zones.filter(
    (zone) => !zone.floor_id || floor === "all" || zone.floor_id === floor,
  );

  function chooseHotspot(hotspot: Hotspot) {
    setSelected(hotspot);
    onHotspot?.(hotspot);
    track("viewer_hotspot_selected", { hotspotId: hotspot.id }, propertyId);
  }

  function changeMode(mode: ViewMode) {
    setViewMode(mode);
    if (mode === "walk") setShowRoof(false);
    track("viewer_mode_changed", { mode }, propertyId);
  }

  if (!started) {
    return (
      <div className="viewer-shell viewer-shell-preview">
        <div
          className="viewer-poster"
          style={{
            backgroundImage: `url(${model.poster_url || "/images/property-placeholder.svg"})`,
          }}
        >
          <div className="stack viewer-poster-content">
            <span className="badge badge-brand">Dollhouse 3D tương tác</span>
            <h2>Khám phá toàn bộ căn nhà theo góc nhìn kiến trúc</h2>
            <p>
              Xoay, phóng to, tách tầng, ẩn mái và chọn từng phòng để hỏi trợ lý Nestora.
            </p>
            <button
              className="btn btn-primary"
              onClick={() => {
                setStarted(true);
                track("viewer_started", {}, propertyId);
              }}
            >
              Bắt đầu xem 3D
            </button>
          </div>
        </div>
      </div>
    );
  }

  const cameraConfig =
    viewMode === "dollhouse"
      ? { position: defaultPosition, zoom: cameraZoom, near: 0.1, far: 500 }
      : { position: defaultPosition, fov: viewMode === "walk" ? 65 : 45, near: 0.1, far: 500 };

  return (
    <div className="viewer-shell viewer-shell-active" ref={shell}>
      <div className="viewer-canvas">
        <ViewerErrorBoundary poster={model.poster_url}>
          <Canvas
            key={`${reset}-${viewMode}`}
            orthographic={viewMode === "dollhouse"}
            shadows
            dpr={dpr}
            camera={cameraConfig}
            gl={{ antialias: quality !== "low", powerPreference: "high-performance" }}
          >
            <color attach="background" args={["#eef3f0"]} />
            <ambientLight intensity={1.45} />
            <hemisphereLight intensity={0.9} color="#ffffff" groundColor="#a7b5ae" />
            <directionalLight position={[10, 16, 8]} intensity={2.4} castShadow />
            <Suspense fallback={<Html center className="viewer-loading">Đang tải mô hình…</Html>}>
              <Bounds fit clip observe margin={viewMode === "dollhouse" ? 1.18 : 1.35}>
                <SceneModel
                  model={model}
                  activeFloor={floor}
                  showFurniture={showFurniture}
                  showRoof={showRoof}
                  explodeFloors={explodeFloors}
                  onHotspot={chooseHotspot}
                />
              </Bounds>
              <Environment preset="apartment" />
              <ContactShadows
                position={[0, -0.25, 0]}
                opacity={0.34}
                scale={45}
                blur={2.8}
                far={25}
              />
            </Suspense>
            {viewMode !== "walk" && (
              <OrbitControls
                makeDefault
                target={
                  selected ? vector3(selected.position, defaultTarget) : defaultTarget
                }
                minDistance={2.5}
                maxDistance={55}
                minPolarAngle={0.15}
                maxPolarAngle={Math.PI / 2.02}
                enableDamping
                dampingFactor={0.08}
              />
            )}
            <WalkController enabled={viewMode === "walk"} zones={activeZones} onPosition={setPosition} />
            <CameraFocus hotspot={selected} />
          </Canvas>
        </ViewerErrorBoundary>

        <div className="viewer-status-row">
          <span className="viewer-status-pill">● Live 3D</span>
          <span className="viewer-status-pill viewer-status-pill-light">
            {viewMode === "dollhouse" ? "Dollhouse" : viewMode === "walk" ? "Đi bộ" : "Orbit"}
          </span>
        </div>
        <MiniMap zones={activeZones} position={position} />
        {selected && (
          <div className="viewer-hotspot-card card card-padded">
            <div className="row viewer-hotspot-title">
              <strong>{selected.label}</strong>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>
                ✕
              </button>
            </div>
            <p className="muted">{selected.description || "Chưa có mô tả."}</p>
          </div>
        )}
      </div>

      <div className="viewer-toolbar" aria-label="Điều khiển mô hình 3D">
        <select
          value={floor}
          onChange={(event) => {
            setFloor(event.target.value);
            setSelected(null);
            track("viewer_floor_changed", { floorId: event.target.value }, propertyId);
          }}
          aria-label="Chọn tầng"
        >
          <option value="all">Tất cả tầng</option>
          {model.floors.map((item) => (
            <option value={item.id} key={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={viewMode === "dollhouse" ? "active" : ""}
          onClick={() => changeMode("dollhouse")}
        >
          Dollhouse
        </button>
        <button
          type="button"
          className={viewMode === "orbit" ? "active" : ""}
          onClick={() => changeMode("orbit")}
        >
          Xoay tự do
        </button>
        <button
          type="button"
          className={viewMode === "walk" ? "active" : ""}
          onClick={() => changeMode("walk")}
        >
          {viewMode === "walk" ? "Đang đi bộ" : "Đi bộ"}
        </button>
        <button type="button" onClick={() => setShowFurniture((value) => !value)}>
          {showFurniture ? "Ẩn" : "Hiện"} nội thất
        </button>
        <button type="button" onClick={() => setShowRoof((value) => !value)}>
          {showRoof ? "Ẩn mái" : "Hiện mái"}
        </button>
        {model.floors.length > 1 && (
          <button type="button" onClick={() => setExplodeFloors((value) => !value)}>
            {explodeFloors ? "Ghép tầng" : "Tách tầng"}
          </button>
        )}
        <select
          value={quality}
          onChange={(event) => setQuality(event.target.value as typeof quality)}
          aria-label="Chất lượng hiển thị"
        >
          <option value="low">Chất lượng thấp</option>
          <option value="medium">Cân bằng</option>
          <option value="high">Chất lượng cao</option>
        </select>
        <button
          type="button"
          onClick={() => {
            setSelected(null);
            setReset((value) => value + 1);
          }}
        >
          Reset camera
        </button>
        <button type="button" onClick={() => shell.current?.requestFullscreen()}>
          Toàn màn hình
        </button>
      </div>
      {viewMode === "walk" && (
        <div className="viewer-walk-help">
          Nhấn vào viewer để khóa chuột. Dùng W/A/S/D để di chuyển và Esc để thoát.
        </div>
      )}
    </div>
  );
}
