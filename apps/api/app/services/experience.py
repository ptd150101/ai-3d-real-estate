from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from typing import Any

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    BrochureAsset,
    ModelNavigationZone,
    PanoramaHotspot,
    PanoramaLink,
    PanoramaScene,
    Property,
)
from .storage import save_local_bytes, save_s3_bytes


def panorama_graph(db: Session, property_id: str, *, include_unpublished: bool = False) -> dict[str, Any]:
    stmt = select(PanoramaScene).where(PanoramaScene.property_id == property_id)
    if not include_unpublished:
        stmt = stmt.where(PanoramaScene.published.is_(True))
    scenes = list(db.scalars(stmt.order_by(PanoramaScene.sort_order, PanoramaScene.created_at)))
    scene_ids = [x.id for x in scenes]
    links = list(db.scalars(select(PanoramaLink).where(PanoramaLink.source_scene_id.in_(scene_ids)))) if scene_ids else []
    hotspots = list(db.scalars(select(PanoramaHotspot).where(PanoramaHotspot.scene_id.in_(scene_ids)))) if scene_ids else []
    zones = list(db.scalars(select(ModelNavigationZone).where(ModelNavigationZone.property_id == property_id, ModelNavigationZone.active.is_(True))))
    return {
        "scenes": [{
            "id": x.id, "property_id": x.property_id, "floor_id": x.floor_id, "name": x.name,
            "image_url": x.image_url, "thumbnail_url": x.thumbnail_url, "initial_yaw": x.initial_yaw,
            "initial_pitch": x.initial_pitch, "initial_fov": x.initial_fov, "sort_order": x.sort_order,
            "published": x.published, "metadata_json": x.metadata_json,
        } for x in scenes],
        "links": [{"id": x.id, "source_scene_id": x.source_scene_id, "target_scene_id": x.target_scene_id, "yaw": x.yaw, "pitch": x.pitch, "label": x.label} for x in links],
        "hotspots": [{"id": x.id, "scene_id": x.scene_id, "yaw": x.yaw, "pitch": x.pitch, "label": x.label, "description": x.description, "hotspot_type": x.hotspot_type, "metadata_json": x.metadata_json} for x in hotspots],
        "navigation_zones": [{"id": x.id, "floor_id": x.floor_id, "name": x.name, "zone_type": x.zone_type, "points_json": x.points_json, "min_y": x.min_y, "max_y": x.max_y} for x in zones],
    }


def _qr_png(url: str) -> bytes:
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _build_pdf(property_obj: Property, site_url: str) -> bytes:
    buffer = io.BytesIO()
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", font_path))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold_path))
        body_font, bold_font = "DejaVu", "DejaVu-Bold"
    except Exception:
        body_font, bold_font = "Helvetica", "Helvetica-Bold"
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    styles["BodyText"].fontName = body_font
    styles["Heading4"].fontName = bold_font
    styles.add(ParagraphStyle(name="TitleVN", parent=styles["Title"], fontName=bold_font, fontSize=22, leading=27, textColor=colors.HexColor("#146047")))
    styles.add(ParagraphStyle(name="CenterSmall", parent=styles["BodyText"], alignment=TA_CENTER, fontSize=8))
    story: list[Any] = [
        Paragraph("NESTORA — PROPERTY BROCHURE", styles["Heading4"]),
        Spacer(1, 6*mm),
        Paragraph(property_obj.title, styles["TitleVN"]),
        Spacer(1, 3*mm),
        Paragraph(f"{property_obj.address}, {property_obj.district}, {property_obj.city}", styles["BodyText"]),
        Spacer(1, 5*mm),
    ]
    price = f"{property_obj.price:,.0f} {property_obj.currency}".replace(",", ".")
    facts = [
        ["Giá", price], ["Diện tích", f"{property_obj.area_m2:g} m²"],
        ["Phòng ngủ", str(property_obj.bedrooms)], ["Phòng tắm", str(property_obj.bathrooms)],
        ["Pháp lý", property_obj.legal_status or "Chưa cập nhật"], ["Nội thất", property_obj.furnishing or "Chưa cập nhật"],
    ]
    table = Table(facts, colWidths=[42*mm, 115*mm])
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#d9e2de")),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#e9f5f0")),
        ("FONTNAME", (0,0), (0,-1), bold_font),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("PADDING", (0,0), (-1,-1), 7),
    ]))
    story.extend([table, Spacer(1, 7*mm), Paragraph(property_obj.description, styles["BodyText"]), Spacer(1, 8*mm)])
    qr = Image(io.BytesIO(_qr_png(f"{site_url.rstrip('/')}/properties/{property_obj.slug}")), width=34*mm, height=34*mm)
    qr_table = Table([[qr, Paragraph("Quét mã để mở trang chi tiết, tour 3D, panorama và chatbot theo ngữ cảnh.<br/><br/><b>Dữ liệu:</b> " + datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"), styles["BodyText"])]], colWidths=[42*mm, 115*mm])
    story.extend([qr_table, Spacer(1, 5*mm), Paragraph("Thông tin trong brochure mang tính tham khảo. Hãy đối chiếu hồ sơ pháp lý và điều kiện giao dịch với bên có thẩm quyền.", styles["CenterSmall"])])
    doc.build(story)
    return buffer.getvalue()


def generate_brochure(db: Session, property_id: str, template_version: str = "v1", force: bool = False) -> dict[str, Any]:
    property_obj = db.get(Property, property_id)
    if not property_obj:
        raise ValueError("Property not found")
    cache_key = hashlib.sha256(f"{property_obj.id}:{property_obj.updated_at.isoformat()}:{template_version}".encode()).hexdigest()
    existing = db.scalar(select(BrochureAsset).where(BrochureAsset.property_id == property_id, BrochureAsset.checksum == cache_key, BrochureAsset.status == "ready"))
    if existing and not force:
        return {"id": existing.id, "property_id": existing.property_id, "storage_url": existing.storage_url, "checksum": existing.checksum, "template_version": existing.template_version, "status": existing.status, "generated_at": existing.generated_at}
    data = _build_pdf(property_obj, get_settings().site_url)
    filename = f"{property_obj.slug}-{template_version}.pdf"
    settings = get_settings()
    if settings.storage_backend == "s3":
        url, _, _ = save_s3_bytes(data, filename, "brochures", "application/pdf")
    else:
        url, _, _ = save_local_bytes(data, filename, "brochures", "application/pdf")
    item = BrochureAsset(property_id=property_id, storage_url=url, checksum=cache_key, template_version=template_version, status="ready", generated_at=datetime.now(timezone.utc))
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "property_id": item.property_id, "storage_url": item.storage_url, "checksum": item.checksum, "template_version": item.template_version, "status": item.status, "generated_at": item.generated_at}
