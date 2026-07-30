from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Agency, Agent, KnowledgeDocument, NearbyPlace, Project, Property, PropertyDocument, PropertyFeature, PropertyFloor, PropertyHotspot, PropertyMedia, PropertyModel3D, User
from .security import hash_password
from .services.rag import index_document


def seed_database(db: Session) -> None:
    if db.scalar(select(User).limit(1)): return
    admin_password = os.getenv("SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(32)
    buyer_password = os.getenv("SEED_BUYER_PASSWORD") or secrets.token_urlsafe(32)
    agent_password = os.getenv("SEED_AGENT_PASSWORD") or secrets.token_urlsafe(32)
    admin = User(email="admin@nestora.vn", full_name="Nestora Admin", password_hash=hash_password(admin_password), role="admin", phone="0900000000")
    buyer = User(email="buyer@nestora.vn", full_name="Nguyễn Minh Anh", password_hash=hash_password(buyer_password), role="buyer", phone="0912345678")
    db.add_all([admin, buyer]); db.flush()
    agency = Agency(name="Nestora Prime", slug="nestora-prime", description="Đơn vị môi giới bất động sản được xác minh.", verified=True)
    db.add(agency); db.flush()
    agent_user = User(email="agent@nestora.vn", full_name="Trần Hoàng Nam", password_hash=hash_password(agent_password), role="agent", phone="0987654321")
    db.add(agent_user); db.flush()
    agent = Agent(user_id=agent_user.id, agency_id=agency.id, display_name="Trần Hoàng Nam", phone="0987654321", email="agent@nestora.vn", bio="Chuyên nhà phố và căn hộ cao cấp Hà Nội.", license_number="HN-REA-2026-001", verified=True, rating=4.9)
    db.add(agent); db.flush()
    project = Project(name="Westlake Residence", slug="westlake-residence", developer="Nestora Development", description="Khu căn hộ ven Hồ Tây với hệ tiện ích cao cấp.", city="Hà Nội", district="Tây Hồ", address="Đường Võ Chí Công, Tây Hồ, Hà Nội", latitude=21.066, longitude=105.801, status="selling", cover_url="https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=1600&q=80")
    db.add(project); db.flush()
    samples = [
        dict(slug="nha-pho-hien-dai-cau-giay", title="Nhà phố hiện đại 4 tầng tại Cầu Giấy", property_type="townhouse", price=12_500_000_000, area_m2=120, bedrooms=4, bathrooms=3, floors_count=4, parking_spaces=1, address="Ngõ 68 Trần Thái Tông", ward="Dịch Vọng Hậu", district="Cầu Giấy", city="Hà Nội", latitude=21.0349, longitude=105.7877, legal_status="Sổ đỏ chính chủ", furnishing="Đầy đủ", description="Nhà phố thiết kế mở, gara ô tô, phòng khách nhiều ánh sáng và sân thượng xanh.", year_built=2024, direction="Đông Nam", is_featured=True, is_verified=True, is_owner_listing=False, has_3d=True, project_id=None, image="https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1600&q=80"),
        dict(slug="can-ho-3pn-view-ho-tay", title="Căn hộ 3PN view Hồ Tây", property_type="apartment", price=8_900_000_000, area_m2=108, bedrooms=3, bathrooms=2, floors_count=1, parking_spaces=1, address="Võ Chí Công", ward="Xuân La", district="Tây Hồ", city="Hà Nội", latitude=21.066, longitude=105.801, legal_status="Sở hữu lâu dài", furnishing="Nội thất cao cấp", description="Căn hộ góc ba phòng ngủ, ban công hướng hồ.", year_built=2025, direction="Tây Bắc", is_featured=True, is_verified=True, is_owner_listing=False, has_3d=True, project_id=project.id, image="https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=1600&q=80"),
        dict(slug="biet-thu-san-vuon-long-bien", title="Biệt thự sân vườn Long Biên", property_type="villa", price=18_200_000_000, area_m2=240, bedrooms=5, bathrooms=4, floors_count=3, parking_spaces=2, address="Khu đô thị Việt Hưng", ward="Việt Hưng", district="Long Biên", city="Hà Nội", latitude=21.0555, longitude=105.915, legal_status="Sổ đỏ chính chủ", furnishing="Cơ bản", description="Biệt thự đơn lập có sân vườn và gara hai xe.", year_built=2023, direction="Nam", is_featured=True, is_verified=True, is_owner_listing=True, has_3d=False, project_id=None, image="https://images.unsplash.com/photo-1600047509807-ba8f99d2cdde?auto=format&fit=crop&w=1600&q=80"),
        dict(slug="chung-cu-2pn-nam-tu-liem", title="Căn hộ 2PN gần Mỹ Đình", property_type="apartment", price=4_600_000_000, area_m2=76, bedrooms=2, bathrooms=2, floors_count=1, parking_spaces=1, address="Đường Lê Quang Đạo", ward="Mễ Trì", district="Nam Từ Liêm", city="Hà Nội", latitude=21.011, longitude=105.769, legal_status="Hợp đồng mua bán", furnishing="Đầy đủ", description="Căn hộ hai phòng ngủ phù hợp gia đình trẻ.", year_built=2022, direction="Đông", is_featured=False, is_verified=False, is_owner_listing=True, has_3d=False, project_id=None, image="https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=1600&q=80"),
        dict(slug="shophouse-ha-dong", title="Shophouse kinh doanh Hà Đông", property_type="shophouse", price=14_800_000_000, area_m2=95, bedrooms=3, bathrooms=4, floors_count=5, parking_spaces=1, address="Khu đô thị Văn Phú", ward="Phú La", district="Hà Đông", city="Hà Nội", latitude=20.962, longitude=105.776, legal_status="Sổ đỏ lâu dài", furnishing="Thô", description="Shophouse mặt tiền rộng, phù hợp kinh doanh.", year_built=2024, direction="Bắc", is_featured=False, is_verified=True, is_owner_listing=False, has_3d=False, project_id=None, image="https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1600&q=80"),
        dict(slug="nha-thue-tay-ho-co-3d", title="Nhà thuê Tây Hồ có tour 3D", transaction_type="rent", property_type="townhouse", price=45_000_000, area_m2=150, bedrooms=4, bathrooms=3, floors_count=3, parking_spaces=1, address="Đường Tô Ngọc Vân", ward="Quảng An", district="Tây Hồ", city="Hà Nội", latitude=21.071, longitude=105.825, legal_status="Hợp đồng thuê chuẩn", furnishing="Đầy đủ", description="Nhà thuê hiện đại gần Hồ Tây.", year_built=2023, direction="Đông Nam", is_featured=False, is_verified=True, is_owner_listing=True, has_3d=True, project_id=None, image="https://images.unsplash.com/photo-1600566753190-17f0baa2a6c3?auto=format&fit=crop&w=1600&q=80"),
    ]
    now = datetime.now(timezone.utc)
    for idx, sample in enumerate(samples):
        image = sample.pop("image"); transaction_type = sample.pop("transaction_type", "sale")
        item = Property(**sample, transaction_type=transaction_type, status="published", currency="VND", agent_id=agent.id, owner_id=admin.id, published_at=now-timedelta(days=idx), verified_at=now-timedelta(days=idx) if sample.get("is_verified") else None, expires_at=now+timedelta(days=90))
        item.features = [PropertyFeature(name=x, category="amenity") for x in ["Gara ô tô", "Ban công", "Điều hòa", "An ninh 24/7"]]
        item.media = [PropertyMedia(media_type="image", url=image, thumbnail_url=image, alt_text=f"Ảnh {item.title}", sort_order=0), PropertyMedia(media_type="image", url="https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=1600&q=80", alt_text=f"Nội thất {item.title}", sort_order=1)]
        if item.has_3d:
            model = PropertyModel3D(model_url="/models/demo-house.glb", poster_url=image, format="glb", file_size_bytes=18000, processing_status="ready", default_camera={"position":[8,5,8],"target":[0,1,0]}, quality_presets={"low":{"dpr":1},"medium":{"dpr":1.5},"high":{"dpr":2}})
            model.floors = [PropertyFloor(name="Tầng 1", sort_order=0, object_names=["Ground","Floor1","Walls1"], furniture_object_names=["Furniture1"], camera={"position":[6,3,6],"target":[0,1,0]}), PropertyFloor(name="Tầng 2", sort_order=1, object_names=["Floor2","Walls2"], furniture_object_names=["Furniture2"], camera={"position":[6,5,6],"target":[0,3,0]})]
            model.hotspots = [PropertyHotspot(label="Phòng khách", description="Không gian mở khoảng 28 m².", position=[0,1.3,1.2], room_type="living_room"), PropertyHotspot(label="Phòng bếp", description="Bếp liên thông khu ăn uống.", position=[-1.8,1.2,-0.5], room_type="kitchen"), PropertyHotspot(label="Phòng ngủ chính", description="Có vệ sinh riêng và ban công.", position=[0.8,3.4,0], room_type="master_bedroom")]
            item.model_3d = model
        item.documents = [PropertyDocument(document_type="legal", title="Thông tin pháp lý", url="/documents/demo-legal.pdf", verified=item.is_verified)]
        db.add(item); db.flush()
        db.add_all([NearbyPlace(property_id=item.id, name="Trường học gần nhất", category="school", latitude=item.latitude+0.002, longitude=item.longitude+0.001, distance_m=350), NearbyPlace(property_id=item.id, name="Siêu thị tiện lợi", category="supermarket", latitude=item.latitude-0.001, longitude=item.longitude+0.001, distance_m=220), NearbyPlace(property_id=item.id, name="Bệnh viện/Phòng khám", category="hospital", latitude=item.latitude+0.004, longitude=item.longitude-0.002, distance_m=780)])
        doc = KnowledgeDocument(property_id=item.id, project_id=item.project_id, document_type="listing", title=f"Dữ liệu xác minh - {item.title}", source_url=f"/properties/{item.slug}", content=f"{item.title}. Giá {item.price} VND. Diện tích {item.area_m2} m². Có {item.bedrooms} phòng ngủ và {item.bathrooms} phòng tắm. Địa chỉ {item.address}, {item.district}, {item.city}. Pháp lý: {item.legal_status}. Mô tả: {item.description}", verified=item.is_verified)
        db.add(doc); db.flush(); index_document(db, doc)
    db.commit()
