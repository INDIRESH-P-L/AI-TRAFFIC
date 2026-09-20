"""TRAFFICINTEL AI - API Integration & Grounding Tests
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import Base, engine, SessionLocal
from app.models.entities import User, Intersection
from app.core.security import get_password_hash

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Create test admin if not present
    user = db.query(User).filter(User.username == "test_admin").first()
    if not user:
        user = User(
            username="test_admin",
            email="test_admin@trafficintel.gov",
            hashed_password=get_password_hash("SecretPass123!"),
            full_name="Test Operator",
            role="ADMIN"
        )
        db.add(user)
        db.commit()
    db.close()
    yield


def test_auth_login_success():
    resp = client.post("/api/v1/auth/login", data={"username": "test_admin", "password": "SecretPass123!"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["role"] == "ADMIN"


def test_auth_login_invalid_password():
    resp = client.post("/api/v1/auth/login", data={"username": "test_admin", "password": "WrongPassword!"})
    assert resp.status_code == 401


def test_dashboard_summary_honest_state():
    # Login first
    login_resp = client.post("/api/v1/auth/login", data={"username": "test_admin", "password": "SecretPass123!"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "system_status" in data
    assert "infrastructure" in data
    assert data["infrastructure"]["controllers"]["status"] in ["NOT_CONFIGURED", "CONNECTED", "NOT_CONNECTED"]


def test_copilot_truthful_unobserved_intersection():
    """Rule #66: If user queries an unmonitored intersection, copilot must state no live telemetry exists."""
    login_resp = client.post("/api/v1/auth/login", data={"username": "test_admin", "password": "SecretPass123!"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Add a configured intersection with zero telemetry
    db = SessionLocal()
    inter = db.query(Intersection).filter(Intersection.code == "JCT-303").first()
    if not inter:
        inter = Intersection(
            name="Junction 303",
            code="JCT-303",
            latitude=37.7749,
            longitude=-122.4194,
            operational_status="HEALTHY"
        )
        db.add(inter)
        db.commit()
        db.refresh(inter)
    db.close()

    resp = client.post("/api/v1/copilot/query", json={"query": "Why is Junction 303 congested?"}, headers=headers)
    assert resp.status_code == 200
    ans = resp.json()["answer"]
    assert "no live traffic telemetry available" in ans
