from __future__ import annotations

import json
import math
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "demo"
MODEL_PROXY_PREFIX = "/api/backend/demo-assets/models"
IMAGE_PROXY_PREFIX = "/api/backend/demo-assets/images"


@lru_cache
def model_templates() -> dict[str, dict[str, Any]]:
    rows = json.loads((FIXTURE_ROOT / "model_templates.json").read_text(encoding="utf-8"))
    return {str(row["id"]): row for row in rows}


def get_model_template(template_id: str) -> dict[str, Any]:
    try:
        return model_templates()[template_id]
    except KeyError as exc:
        raise KeyError(f"Unknown demo model template: {template_id}") from exc


def demo_model_url(template_id: str) -> str:
    return f"{MODEL_PROXY_PREFIX}/{template_id}.glb"


def demo_poster_url(template_id: str) -> str:
    return f"{IMAGE_PROXY_PREFIX}/model/{template_id}.svg"


def select_model_template(property_type: str, bedrooms: int, floors_count: int) -> str:
    if property_type == "studio":
        return "studio-compact"
    if property_type == "apartment":
        if bedrooms <= 2:
            return "apartment-2br"
        if bedrooms == 3:
            return "apartment-3br"
        return "apartment-luxury"
    if property_type == "penthouse":
        return "apartment-luxury"
    if property_type == "villa":
        return "villa-garden"
    if property_type == "shophouse":
        return "shophouse"
    return "townhouse-3-floor" if floors_count <= 3 else "townhouse-4-floor"


def template_floor_payload(template_id: str) -> list[dict[str, Any]]:
    template = get_model_template(template_id)
    floors = int(template.get("floors", 1))
    rows: list[dict[str, Any]] = []
    for index in range(1, floors + 1):
        y = (index - 1) * 3.2
        rows.append(
            {
                "name": "Căn hộ" if floors == 1 else f"Tầng {index}",
                "sort_order": index - 1,
                "object_names": [f"Floor{index}", f"Walls{index}", f"Roof{index}"],
                "furniture_object_names": [f"Furniture{index}"],
                "camera": {
                    "mode": "orthographic",
                    "position": [10 + index, 8 + y, 10 + index],
                    "target": [0, y + 0.8, 0],
                    "zoom": max(34, int(template.get("camera", {}).get("zoom", 48))),
                },
            }
        )
    return rows


def template_hotspot_payload(template_id: str) -> list[dict[str, Any]]:
    template = get_model_template(template_id)
    floors = max(1, int(template.get("floors", 1)))
    rooms = list(template.get("rooms", []))
    result: list[dict[str, Any]] = []
    for index, room in enumerate(rooms):
        label, room_type, x, z = room
        floor_index = index % floors
        level = floor_index * 3.2
        result.append(
            {
                "floor_index": floor_index,
                "label": str(label),
                "description": f"Khu vực {label.lower()} trong mô hình 3D demo, có thể chọn để hỏi trợ lý Nestora.",
                "position": [float(x), level + 1.35, float(z)],
                "camera_position": [float(x) + 4.5, level + 3.2, float(z) + 4.5],
                "room_type": str(room_type),
                "metadata_json": {"template_id": template_id, "demo": True},
            }
        )
    return result


# Unit cube: 24 vertices so every face has a stable normal.
_CUBE_POSITIONS = [
    # +X
    (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5), (0.5, -0.5, 0.5),
    # -X
    (-0.5, -0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5, -0.5), (-0.5, -0.5, -0.5),
    # +Y
    (-0.5, 0.5, -0.5), (-0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5),
    # -Y
    (-0.5, -0.5, 0.5), (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5),
    # +Z
    (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    # -Z
    (0.5, -0.5, -0.5), (-0.5, -0.5, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5),
]
_CUBE_NORMALS = (
    [(1.0, 0.0, 0.0)] * 4
    + [(-1.0, 0.0, 0.0)] * 4
    + [(0.0, 1.0, 0.0)] * 4
    + [(0.0, -1.0, 0.0)] * 4
    + [(0.0, 0.0, 1.0)] * 4
    + [(0.0, 0.0, -1.0)] * 4
)
_CUBE_INDICES = [
    0, 1, 2, 0, 2, 3,
    4, 5, 6, 4, 6, 7,
    8, 9, 10, 8, 10, 11,
    12, 13, 14, 12, 14, 15,
    16, 17, 18, 16, 18, 19,
    20, 21, 22, 20, 22, 23,
]


def _pad4(data: bytes, pad: bytes = b"\x00") -> bytes:
    return data + pad * ((4 - len(data) % 4) % 4)


def _material(name: str, color: tuple[float, float, float, float], *, roughness: float = 0.8) -> dict[str, Any]:
    return {
        "name": name,
        "pbrMetallicRoughness": {
            "baseColorFactor": list(color),
            "metallicFactor": 0.0,
            "roughnessFactor": roughness,
        },
        "doubleSided": True,
    }


def _node(name: str, mesh: int, translation: list[float], scale: list[float]) -> dict[str, Any]:
    return {"name": name, "mesh": mesh, "translation": translation, "scale": scale}


@lru_cache(maxsize=16)
def build_demo_glb(template_id: str) -> bytes:
    template = get_model_template(template_id)
    width = float(template.get("width", 10.0))
    depth = float(template.get("depth", 8.0))
    floors = max(1, int(template.get("floors", 1)))
    rooms = list(template.get("rooms", []))

    positions = b"".join(struct.pack("<3f", *value) for value in _CUBE_POSITIONS)
    normals = b"".join(struct.pack("<3f", *value) for value in _CUBE_NORMALS)
    indices = b"".join(struct.pack("<H", value) for value in _CUBE_INDICES)
    positions_offset = 0
    normals_offset = len(positions)
    indices_offset = normals_offset + len(normals)
    binary = _pad4(positions + normals + indices)

    materials = [
        _material("Floor oak", (0.66, 0.46, 0.29, 1.0)),
        _material("Warm white walls", (0.92, 0.93, 0.90, 1.0)),
        _material("Furniture green", (0.11, 0.43, 0.34, 1.0), roughness=0.65),
        _material("Furniture terracotta", (0.77, 0.35, 0.23, 1.0), roughness=0.7),
        _material("Furniture blue", (0.20, 0.43, 0.66, 1.0), roughness=0.65),
        _material("Roof", (0.28, 0.31, 0.34, 0.88), roughness=0.9),
        _material("Garden", (0.24, 0.55, 0.28, 1.0), roughness=1.0),
        _material("Water", (0.20, 0.62, 0.80, 0.72), roughness=0.2),
        _material("Glass", (0.60, 0.83, 0.92, 0.42), roughness=0.15),
    ]
    meshes = [
        {
            "name": f"Cube material {index}",
            "primitives": [
                {
                    "attributes": {"POSITION": 0, "NORMAL": 1},
                    "indices": 2,
                    "material": index,
                }
            ],
        }
        for index in range(len(materials))
    ]

    nodes: list[dict[str, Any]] = []
    root_children: list[int] = []

    def add(node: dict[str, Any]) -> None:
        root_children.append(len(nodes))
        nodes.append(node)

    # A slightly oversized base makes the model read as a physical dollhouse.
    add(_node("SiteBase", 6, [0.0, -0.18, 0.0], [width + 2.0, 0.18, depth + 2.0]))

    room_palette = [2, 3, 4]
    for floor_index in range(floors):
        number = floor_index + 1
        base_y = floor_index * 3.2
        add(_node(f"Floor{number}_Slab", 0, [0.0, base_y, 0.0], [width, 0.22, depth]))
        # Keep the front open, creating the classic real-estate dollhouse cutaway.
        wall_height = 2.75
        wall_thickness = 0.16
        add(_node(f"Walls{number}_Back", 1, [0.0, base_y + wall_height / 2, -depth / 2], [width, wall_height, wall_thickness]))
        add(_node(f"Walls{number}_Left", 1, [-width / 2, base_y + wall_height / 2, 0.0], [wall_thickness, wall_height, depth]))
        add(_node(f"Walls{number}_Right", 1, [width / 2, base_y + wall_height / 2, 0.0], [wall_thickness, wall_height, depth]))
        # Low front curb keeps the silhouette but does not hide the rooms.
        add(_node(f"Walls{number}_FrontCurb", 1, [0.0, base_y + 0.35, depth / 2], [width, 0.7, wall_thickness]))

        floor_rooms = [room for idx, room in enumerate(rooms) if idx % floors == floor_index]
        if not floor_rooms:
            floor_rooms = rooms[:1]
        for room_index, room in enumerate(floor_rooms):
            label, room_type, x, z = room
            x = float(x)
            z = float(z)
            material_index = room_palette[room_index % len(room_palette)]
            # Main furniture/island block.
            size_x = 1.4 + (room_index % 2) * 0.5
            size_z = 0.9 + ((room_index + 1) % 2) * 0.5
            add(_node(f"Furniture{number}_{room_type}_{room_index + 1}", material_index, [x, base_y + 0.48, z], [size_x, 0.72, size_z]))
            # Secondary accent creates more visual variety without heavy geometry.
            add(_node(f"Furniture{number}_{room_type}_{room_index + 1}_Accent", (material_index + 1 - 2) % 3 + 2, [x + 0.55, base_y + 0.92, z - 0.25], [0.55, 0.22, 0.55]))
            # Partition close to each room, alternating orientation.
            if room_index < max(1, len(floor_rooms) - 1):
                if room_index % 2 == 0:
                    add(_node(f"Walls{number}_Partition_{room_index + 1}", 1, [x - 1.15, base_y + 1.15, z], [0.12, 2.3, 3.0]))
                else:
                    add(_node(f"Walls{number}_Partition_{room_index + 1}", 1, [x, base_y + 1.15, z + 1.05], [3.0, 2.3, 0.12]))

        # Windows on the back wall.
        for window_index in range(3):
            wx = -width * 0.28 + window_index * width * 0.28
            add(_node(f"Walls{number}_Window_{window_index + 1}", 8, [wx, base_y + 1.55, -depth / 2 + 0.1], [1.25, 1.05, 0.06]))

        roof_y = base_y + 2.95
        add(_node(f"Roof{number}", 5, [0.0, roof_y, 0.0], [width + 0.25, 0.16, depth + 0.25]))

    if template_id == "villa-garden":
        add(_node("Garden_Lawn", 6, [width * 0.48, 0.02, depth * 0.38], [5.0, 0.12, 4.4]))
        add(_node("Garden_Pool", 7, [width * 0.38, 0.12, -depth * 0.34], [4.8, 0.18, 2.5]))
        for index in range(4):
            angle = index * math.pi / 2
            add(_node(f"Garden_Tree_{index + 1}", 6, [math.cos(angle) * (width / 2 + 0.5), 0.75, math.sin(angle) * (depth / 2 + 0.5)], [0.55, 1.5, 0.55]))
    if template_id in {"shophouse", "townhouse-4-floor"}:
        for index in range(4):
            add(_node(f"Facade_Column_{index + 1}", 5, [-width / 2 + 0.7 + index * (width - 1.4) / 3, 1.55, depth / 2 + 0.18], [0.22, 3.1, 0.22]))

    root_index = len(nodes)
    nodes.append({"name": f"Demo_{template_id}", "children": root_children})

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "Nestora deterministic demo asset generator"},
        "scene": 0,
        "scenes": [{"name": "Dollhouse", "nodes": [root_index]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": positions_offset, "byteLength": len(positions), "target": 34962},
            {"buffer": 0, "byteOffset": normals_offset, "byteLength": len(normals), "target": 34962},
            {"buffer": 0, "byteOffset": indices_offset, "byteLength": len(indices), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(_CUBE_POSITIONS), "type": "VEC3", "min": [-0.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]},
            {"bufferView": 1, "componentType": 5126, "count": len(_CUBE_NORMALS), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": len(_CUBE_INDICES), "type": "SCALAR", "min": [0], "max": [23]},
        ],
    }
    json_chunk = _pad4(json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), b" ")
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)
    return b"".join(
        [
            b"glTF",
            struct.pack("<I", 2),
            struct.pack("<I", total_length),
            struct.pack("<I", len(json_chunk)),
            b"JSON",
            json_chunk,
            struct.pack("<I", len(binary)),
            b"BIN\x00",
            binary,
        ]
    )


_IMAGE_COLORS: dict[str, tuple[str, str]] = {
    "apartment": ("#d9ebe6", "#146047"),
    "studio": ("#ece4f7", "#6f42a5"),
    "penthouse": ("#e7e3d4", "#866d1d"),
    "townhouse": ("#f2dfd6", "#a94d2f"),
    "villa": ("#dfead7", "#3d6d2f"),
    "shophouse": ("#dce6f3", "#315f8a"),
    "project": ("#e4e8ee", "#35455f"),
    "agent": ("#e8f2ee", "#146047"),
    "brand": ("#e9f5f0", "#0b4030"),
    "model": ("#dce8e2", "#146047"),
}


def build_demo_svg(category: str, asset_key: str) -> bytes:
    background, accent = _IMAGE_COLORS.get(category, ("#e8ecef", "#45515d"))
    seed = sum(ord(char) for char in f"{category}:{asset_key}")
    label = category.replace("-", " ").title()
    if category == "model":
        try:
            label = str(get_model_template(asset_key).get("label", asset_key))
        except KeyError:
            label = asset_key.replace("-", " ").title()
    blocks = []
    for index in range(7):
        x = 90 + ((seed * (index + 3)) % 710)
        y = 90 + ((seed * (index + 7)) % 330)
        width = 90 + ((seed + index * 23) % 150)
        height = 65 + ((seed + index * 31) % 105)
        opacity = 0.10 + (index % 4) * 0.06
        blocks.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="{accent}" opacity="{opacity:.2f}"/>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800" role="img" aria-label="{label}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{background}"/><stop offset="1" stop-color="#ffffff"/></linearGradient>
    <filter id="shadow"><feDropShadow dx="0" dy="16" stdDeviation="18" flood-opacity=".14"/></filter>
  </defs>
  <rect width="1200" height="800" fill="url(#bg)"/>
  <g filter="url(#shadow)"><path d="M180 590 L600 245 L1020 590 L600 720 Z" fill="#fff" stroke="{accent}" stroke-width="8" opacity=".96"/></g>
  <g>{''.join(blocks)}</g>
  <path d="M335 570 L600 350 L870 570 L600 665 Z" fill="none" stroke="{accent}" stroke-width="14" stroke-linejoin="round"/>
  <path d="M600 350 V665 M335 570 H870" stroke="{accent}" stroke-width="7" opacity=".55"/>
  <circle cx="1050" cy="120" r="44" fill="{accent}" opacity=".16"/>
  <text x="72" y="105" font-family="Inter,Arial,sans-serif" font-size="34" font-weight="800" fill="{accent}">NESTORA DEMO</text>
  <text x="72" y="155" font-family="Inter,Arial,sans-serif" font-size="26" fill="#35404a">{label} · {asset_key}</text>
  <text x="72" y="748" font-family="Inter,Arial,sans-serif" font-size="22" fill="#68717d">Local deterministic fixture asset — no external image dependency</text>
</svg>'''
    return svg.encode("utf-8")
