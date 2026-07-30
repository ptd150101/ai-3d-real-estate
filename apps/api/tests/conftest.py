from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["STORAGE_ROOT"] = str(Path(__file__).parent / "test-storage")
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SEED_BUYER_PASSWORD"] = "test-buyer-password"
os.environ["SEED_AGENT_PASSWORD"] = "test-agent-password"

from app.database import Base, get_db
from app.main import app
from app.seed import seed_database

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.create_all(engine)
    with TestingSessionLocal() as db:
        seed_database(db)
    yield
    Base.metadata.drop_all(engine)

def override_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_db

@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture()
def admin_headers(client: TestClient):
    response = client.post("/api/v1/auth/login", json={"email": "admin@nestora.vn", "password": "test-admin-password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

@pytest.fixture()
def buyer_headers(client: TestClient):
    response = client.post("/api/v1/auth/login", json={"email": "buyer@nestora.vn", "password": "test-buyer-password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
