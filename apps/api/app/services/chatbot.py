from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChatMessage, ChatSession, NearbyPlace, Property, PropertyHotspot
from ..schemas import ChatRequest, ChatResponse, Citation, MortgageRequest, ToolResult
from .mortgage import calculate_mortgage
from .rag import retrieve
from .search import parse_money, parse_natural_query, search_properties

PROMPT_INJECTION_MARKERS = ["ignore previous", "ignore all previous", "system prompt", "developer message", "bỏ qua hướng dẫn", "tiết lộ prompt", "jailbreak", "do anything now"]


def format_money(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:g} tỷ đồng"
    return f"{value / 1_000_000:g} triệu đồng"


def suspicious_prompt(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in PROMPT_INJECTION_MARKERS)


def property_dict(p: Property) -> dict[str, Any]:
    cover = p.media[0].thumbnail_url or p.media[0].url if p.media else None
    return {"id": p.id, "slug": p.slug, "title": p.title, "price": p.price, "price_label": format_money(p.price), "area_m2": p.area_m2, "bedrooms": p.bedrooms, "bathrooms": p.bathrooms, "district": p.district, "city": p.city, "address": p.address, "legal_status": p.legal_status, "has_3d": p.has_3d, "cover_url": cover}


def get_property(db: Session, property_id: str | None) -> Property | None:
    if not property_id:
        return None
    return db.scalar(select(Property).where(Property.id == property_id)) or db.scalar(select(Property).where(Property.slug == property_id))


def answer_property_question(db: Session, p: Property, text: str, context_hotspot: str | None) -> tuple[str, list[ToolResult], list[Citation]]:
    lowered = text.lower()
    tool_results = [ToolResult(tool="get_current_property", data=property_dict(p))]
    citations = [Citation(label=f"Dữ liệu đã xác minh của {p.title}", property_id=p.id)]
    if context_hotspot:
        hotspot = db.get(PropertyHotspot, context_hotspot)
        if hotspot:
            return f"Bạn đang xem {hotspot.label}. {hotspot.description or 'Chưa có mô tả chi tiết cho khu vực này.'}", tool_results + [ToolResult(tool="get_hotspot", data={"label": hotspot.label, "description": hotspot.description})], citations
    if any(x in lowered for x in ["giá", "bao nhiêu", "price"]):
        return f"{p.title} đang được niêm yết ở mức {format_money(p.price)}.", tool_results, citations
    if any(x in lowered for x in ["pháp lý", "sổ đỏ", "giấy tờ"]):
        if p.legal_status:
            suffix = " Thông tin này đã được đánh dấu xác minh." if p.is_verified else " Bạn nên yêu cầu môi giới cung cấp bản đối chiếu giấy tờ trước khi giao dịch."
            return f"Tình trạng pháp lý được khai báo là: {p.legal_status}.{suffix}", tool_results, citations
        return "Tin đăng chưa có dữ liệu pháp lý đã xác minh. Mình có thể chuyển yêu cầu cho tư vấn viên.", tool_results, citations
    if any(x in lowered for x in ["diện tích", "phòng ngủ", "phòng tắm", "wc", "mấy phòng"]):
        return f"Căn này rộng {p.area_m2:g} m², gồm {p.bedrooms} phòng ngủ, {p.bathrooms} phòng tắm và {p.floors_count} tầng.", tool_results, citations
    if any(x in lowered for x in ["địa chỉ", "ở đâu", "vị trí"]):
        return f"Bất động sản nằm tại {p.address}, {p.district}, {p.city}.", tool_results, citations
    return f"{p.title} có diện tích {p.area_m2:g} m², giá {format_money(p.price)}, {p.bedrooms} phòng ngủ và pháp lý {p.legal_status or 'chưa cập nhật'}. Bạn có thể hỏi thêm về khoản vay, tiện ích gần nhà hoặc đặt lịch xem.", tool_results, citations


def compare_tool(db: Session, property_ids: list[str]) -> tuple[str, ToolResult]:
    properties = list(db.scalars(select(Property).where(Property.id.in_(property_ids))))
    if len(properties) < 2:
        return "Mình cần ít nhất hai bất động sản hợp lệ để so sánh.", ToolResult(tool="compare_properties", data=[])
    cheapest = min(properties, key=lambda p: p.price)
    largest = max(properties, key=lambda p: p.area_m2)
    best_3d = next((p for p in properties if p.has_3d), None)
    lines = [f"{cheapest.title} có giá thấp nhất ({format_money(cheapest.price)}).", f"{largest.title} có diện tích lớn nhất ({largest.area_m2:g} m²)."]
    if best_3d:
        lines.append(f"{best_3d.title} hỗ trợ trải nghiệm 3D.")
    return " ".join(lines), ToolResult(tool="compare_properties", data=[property_dict(p) for p in properties])


def nearby_tool(db: Session, p: Property, category: str | None = None) -> tuple[str, ToolResult]:
    stmt = select(NearbyPlace).where(NearbyPlace.property_id == p.id)
    if category:
        stmt = stmt.where(NearbyPlace.category == category)
    places = list(db.scalars(stmt.order_by(NearbyPlace.distance_m.asc()).limit(8)))
    if not places:
        return "Chưa có dữ liệu tiện ích lân cận đã xác minh cho căn này.", ToolResult(tool="find_nearby_places", data=[])
    message = "Các địa điểm gần nhất gồm: " + "; ".join(f"{x.name} ({x.distance_m or 0} m)" for x in places[:4]) + "."
    return message, ToolResult(tool="find_nearby_places", data=[{"name": x.name, "category": x.category, "distance_m": x.distance_m} for x in places])


def ensure_session(db: Session, request: ChatRequest, user_id: str | None) -> ChatSession:
    session = db.get(ChatSession, request.session_id) if request.session_id else None
    if not session:
        session = ChatSession(user_id=user_id)
        db.add(session)
        db.flush()
    session.current_property_id = request.context.current_property_id
    session.current_floor_id = request.context.current_floor_id
    session.selected_hotspot_id = request.context.selected_hotspot_id
    session.filters_json = request.context.filters
    return session


async def respond(db: Session, request: ChatRequest, user_id: str | None = None) -> ChatResponse:
    session = ensure_session(db, request, user_id)
    db.add(ChatMessage(session_id=session.id, role="user", content=request.message))
    if suspicious_prompt(request.message):
        answer = "Mình chỉ có thể hỗ trợ tìm hiểu bất động sản và không thể tiết lộ hướng dẫn hệ thống hoặc bỏ qua quy tắc bảo vệ dữ liệu."
        db.add(ChatMessage(session_id=session.id, role="assistant", content=answer))
        db.commit()
        return ChatResponse(session_id=session.id, message=answer)
    text = request.message.strip()
    lowered = text.lower()
    property_obj = get_property(db, request.context.current_property_id)
    tool_results: list[ToolResult] = []
    citations: list[Citation] = []
    disclaimer: str | None = None
    requires_confirmation = False
    if any(x in lowered for x in ["vay", "trả góp", "lãi suất"]):
        price = property_obj.price if property_obj else parse_money(text)
        if not price:
            answer = "Bạn hãy cho mình giá căn nhà hoặc mở một tin đăng trước khi tính khoản vay."
        else:
            down = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
            years = re.search(r"(\d+)\s*năm", lowered)
            rate_matches = re.findall(r"(\d+(?:[.,]\d+)?)\s*%", text)
            args = MortgageRequest(property_price=price, down_payment_percent=float(down.group(1).replace(",", ".")) if down else 30, annual_interest_percent=float(rate_matches[-1].replace(",", ".")) if len(rate_matches) > 1 else 9, term_years=int(years.group(1)) if years else 20)
            result = calculate_mortgage(args)
            answer = f"Khoản vay dự kiến là {format_money(result.principal)}, trả khoảng {result.monthly_payment:,} đồng/tháng trong {args.term_years} năm."
            tool_results.append(ToolResult(tool="calculate_mortgage", data=result.model_dump()))
            disclaimer = result.disclaimer
    elif any(x in lowered for x in ["so sánh", "compare"]):
        ids = re.findall(r"[0-9a-f]{8}-[0-9a-f-]{27,}", text, re.I)
        if property_obj and property_obj.id not in ids:
            ids.insert(0, property_obj.id)
        if len(ids) < 2:
            answer = "Hãy thêm từ hai căn vào danh sách so sánh, sau đó mình sẽ chỉ ra căn rẻ hơn, rộng hơn và có 3D."
        else:
            answer, tool = compare_tool(db, ids[:4]); tool_results.append(tool)
    elif any(x in lowered for x in ["gần", "tiện ích", "trường", "bệnh viện", "siêu thị"]):
        if not property_obj:
            answer = "Bạn hãy mở một bất động sản để mình tìm tiện ích lân cận."
        else:
            category = "school" if "trường" in lowered else "hospital" if "bệnh viện" in lowered else "supermarket" if "siêu thị" in lowered else None
            answer, tool = nearby_tool(db, property_obj, category); tool_results.append(tool)
    elif any(x in lowered for x in ["đặt lịch", "xem nhà", "hẹn xem"]):
        answer = "Mình có thể đặt lịch xem nhà. Vui lòng xác nhận họ tên, số điện thoại và thời gian mong muốn trong biểu mẫu bảo mật."
        tool_results.append(ToolResult(tool="create_viewing_appointment", data={"property_id": property_obj.id if property_obj else None, "needs": ["full_name", "phone", "scheduled_at"]})); requires_confirmation = True
    elif any(x in lowered for x in ["tư vấn viên", "người thật", "gọi lại", "liên hệ"]):
        session.handoff_requested = True
        answer = "Mình đã ghi nhận yêu cầu chuyển sang tư vấn viên. Bạn hãy để lại số điện thoại trong biểu mẫu để đội ngũ liên hệ lại."
        tool_results.append(ToolResult(tool="request_human_support", data={"session_id": session.id})); requires_confirmation = True
    elif any(x in lowered for x in ["tìm", "căn", "nhà", "chung cư", "biệt thự"]) and not property_obj:
        filters, explanation = parse_natural_query(text)
        properties, _ = search_properties(db, filters, page=1, page_size=6)
        answer = explanation + (f" Mình tìm thấy {len(properties)} lựa chọn phù hợp." if properties else " Chưa có kết quả phù hợp; hãy thử nới khoảng giá hoặc khu vực.")
        tool_results.append(ToolResult(tool="search_properties", data=[property_dict(p) for p in properties]))
    elif property_obj:
        answer, tool_results, citations = answer_property_question(db, property_obj, text, request.context.selected_hotspot_id)
        rag = retrieve(db, text, property_id=property_obj.id, project_id=property_obj.project_id, verified_only=True, limit=3)
        if rag and any(x in lowered for x in ["chính sách", "pháp lý", "bàn giao", "phí", "quy hoạch"]):
            answer += " " + rag[0]["content"][:360]
            citations.extend(Citation(label=item["title"], source_url=item["source_url"], document_id=item["document_id"], property_id=item["property_id"]) for item in rag)
    else:
        answer = "Mình có thể tìm nhà theo câu tự nhiên, so sánh các căn, tính khoản vay, kiểm tra tiện ích lân cận và hỗ trợ đặt lịch xem."
    suggested = ["Tìm căn tương tự dưới 10 tỷ", "Tính khoản vay 70% trong 20 năm", "Có trường học nào gần đây?", "Đặt lịch xem nhà"]
    db.add(ChatMessage(session_id=session.id, role="assistant", content=answer, tool_payload={"results": [x.model_dump() for x in tool_results]}, citations=[x.model_dump() for x in citations]))
    db.commit()
    return ChatResponse(session_id=session.id, message=answer, tool_results=tool_results, citations=citations, suggested_questions=suggested, requires_confirmation=requires_confirmation, disclaimer=disclaimer)
