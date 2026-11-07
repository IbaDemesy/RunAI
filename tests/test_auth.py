import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "first:secret,second:other")
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    monkeypatch.delenv("RUNAI_CSP_ENFORCE", raising=False)
    with TestClient(create_app(build_demo_service(delay=0))) as client:
        yield client


@pytest.mark.parametrize("path", [
    "/", "/static/app.js", "/demo/live", "/api/missions/x/events",
    "/api/missions/x/steps/registration/screenshot",
])
def test_protected_routes(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.text == "Authentication required"
    assert response.headers["x-frame-options"] == "DENY"


def test_health_is_public(client):
    assert client.get("/api/health").status_code == 200


def test_second_credentials(client):
    assert client.get("/", auth=("second", "other")).status_code == 200


def test_throttle_uses_forwarded_first_hop_and_expires(client, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("runai.app.auth.time.monotonic", lambda: clock[0])
    for _ in range(5):
        assert client.get("/", auth=("first", "wrong"), headers={
            "X-Forwarded-For": "192.0.2.1, 192.0.2.2",
        }).status_code == 401
    denied = client.get("/", headers={"X-Forwarded-For": "192.0.2.1, 192.0.2.3"})
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "60"
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert client.get("/", auth=("first", "secret"), headers={
        "X-Forwarded-For": "192.0.2.2, 192.0.2.1",
    }).status_code == 200
    assert client.get("/api/health", headers={"X-Forwarded-For": "192.0.2.1"}).status_code == 200
    clock[0] += 60
    assert client.get("/", auth=("first", "secret"), headers={
        "X-Forwarded-For": "192.0.2.1",
    }).status_code == 200


@pytest.mark.parametrize("authorization", ["", "Bearer token", "Basic !not-base64!", "Basic d3Jvbmc6cGFzcw=="])
def test_invalid_authorization(client, authorization):
    assert client.get("/", headers={"Authorization": authorization}).status_code == 401


@pytest.mark.parametrize("credentials", ["missing", "user:", ":pass", "user:pass,", "user:pass,broken"])
def test_invalid_configuration(monkeypatch, credentials):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", credentials)
    with pytest.raises(ValueError, match="user:password"), TestClient(create_app(build_demo_service())):
        pass


@pytest.mark.parametrize("path", ["/", "/api/health"])
def test_headers(client, path):
    response = client.get(path, auth=("first", "secret"))
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "microphone=(self), camera=(), geolocation=()"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy-report-only"]
    assert "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com;" in response.headers["content-security-policy-report-only"]
    assert "content-security-policy" not in response.headers
    if path.startswith("/api/"):
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("enforce", ["0", "1"])
def test_csp_mode_without_auth(monkeypatch, enforce):
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    monkeypatch.setenv("RUNAI_CSP_ENFORCE", enforce)
    with TestClient(create_app(build_demo_service())) as client:
        response = client.get("/")
    expected = "content-security-policy" if enforce == "1" else "content-security-policy-report-only"
    other = "content-security-policy-report-only" if enforce == "1" else "content-security-policy"
    assert expected in response.headers
    assert other not in response.headers
