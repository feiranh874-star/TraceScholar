import asyncio
from dataclasses import replace

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import papers
from app.config import Settings
from app.main import create_app
from app.security import DemoGuardMiddleware


# Test-only credentials; these are not deployment secrets.
TEST_PASSWORD = "test-only-password-2026"
TEST_AUTH = ("viewer", TEST_PASSWORD)


def production_settings(**overrides):
    return replace(
        Settings(
            environment="production", demo_password=TEST_PASSWORD,
            enable_api_docs=False, upload_requests_per_minute=10,
        ),
        **overrides,
    )


def authenticated_client(settings):
    client = TestClient(create_app(settings))
    client.auth = TEST_AUTH
    return client


@pytest.mark.parametrize("path", ["/", "/assets/app.js", "/assets/app.css", "/api/papers", "/docs", "/openapi.json"])
def test_unauthenticated_visitors_cannot_access_ui_or_data(path):
    client = TestClient(create_app(production_settings()))
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")


def test_health_is_public_but_upload_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "data")
    client = TestClient(create_app(production_settings()))
    assert client.get("/health").json()["status"] == "ok"
    response = client.post("/api/papers", files={"file": ("paper.pdf", b"%PDF-", "application/pdf")})
    assert response.status_code == 401
    assert not (papers.DATA_DIR / "papers").exists()


def test_valid_login_serves_ui_and_disables_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "data")
    client = authenticated_client(production_settings())
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    response = client.get("/api/papers")
    assert response.json() == {"items": [], "total": 0}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_authenticated_pdf_survives_app_recreation(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "persistent-data")
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "A public demonstration paper with enough text to test persistent storage.")
        pdf = document.tobytes()

    client = authenticated_client(production_settings())
    upload = client.post(
        "/api/papers", files={"file": ("demo.pdf", pdf, "application/pdf")},
    )
    assert upload.status_code == 201
    paper_id = upload.json()["paper_id"]

    restarted = authenticated_client(production_settings())
    assert restarted.get("/api/papers").json()["total"] == 1
    assert restarted.get(f"/api/papers/{paper_id}/pages/1").json()["text"].startswith("A public demonstration")
    assert restarted.get(f"/api/papers/{paper_id}/chunks").json()["total"] >= 1
    anonymous = TestClient(create_app(production_settings()))
    assert anonymous.get(f"/api/papers/{paper_id}/pages/1").status_code == 401


@pytest.mark.parametrize("authorization", ["Basic !!!", "Bearer test", "Basic /w==", "Basic bm9jb2xvbg=="])
def test_malformed_credentials_fail_without_server_error(authorization):
    client = TestClient(create_app(production_settings()))
    assert client.get("/", headers={"Authorization": authorization}).status_code == 401


def test_wrong_password_is_rejected():
    client = TestClient(create_app(production_settings()))
    assert client.get("/", auth=("viewer", "wrong")).status_code == 401
    assert client.get("/", auth=("different", TEST_PASSWORD)).status_code == 401


@pytest.mark.parametrize("origin", ["https://untrusted.example", "null", "http://["])
def test_cross_site_upload_is_rejected_before_parsing(origin):
    client = authenticated_client(production_settings())
    response = client.post("/api/papers", content=b"anything", headers={"Origin": origin})
    assert response.status_code == 403


def test_same_host_https_origin_works_behind_tls_proxy(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "data")
    client = authenticated_client(production_settings())
    response = client.post(
        "/api/papers", headers={"Origin": "https://testserver"},
        files={"file": ("bad.pdf", b"invalid", "application/pdf")},
    )
    assert response.status_code == 400


def test_production_refuses_missing_password_and_disabled_rate_limit():
    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        create_app(production_settings(demo_password=""))
    with pytest.raises(ValueError, match="rate limit"):
        create_app(production_settings(upload_requests_per_minute=0))


def test_environment_production_defaults(monkeypatch):
    for name in ("ENABLE_API_DOCS", "UPLOAD_REQUESTS_PER_MINUTE", "MAX_REQUEST_BYTES", "MAX_CONCURRENT_UPLOADS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_PASSWORD", TEST_PASSWORD)
    settings = Settings.from_env()
    assert settings.enable_api_docs is False
    assert settings.upload_requests_per_minute == 10
    monkeypatch.delenv("DEMO_PASSWORD")
    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        Settings.from_env()


def test_oversized_body_rejected_before_pdf_handler(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "data")
    client = authenticated_client(production_settings(max_request_bytes=32))
    response = client.post("/api/papers", content=b"x" * 33)
    assert response.status_code == 413
    assert not (papers.DATA_DIR / "papers").exists()


def test_chunked_upload_cannot_bypass_request_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "data")
    application = create_app(production_settings(max_request_bytes=220))

    async def run():
        async def body():
            yield b'--test\r\nContent-Disposition: form-data; name="file"; filename="x.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
            yield b"%PDF-" + b"x" * 100
            yield b"x" * 100
            yield b"\r\n--test--\r\n"

        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", auth=TEST_AUTH) as client:
            return await client.post(
                "/api/papers", content=body(),
                headers={"Content-Type": "multipart/form-data; boundary=test"},
            )

    assert asyncio.run(run()).status_code == 413
    assert not (papers.DATA_DIR / "papers").exists()


def test_upload_rate_limit_is_shared_and_returns_retry_after(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "data")
    client = authenticated_client(production_settings(upload_requests_per_minute=1))
    first = client.post("/api/papers", files={"file": ("bad.pdf", b"invalid", "application/pdf")})
    assert first.status_code == 400
    second = client.post("/api/papers", files={"file": ("bad.pdf", b"invalid", "application/pdf")})
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


def test_failed_auth_rate_limit_does_not_lock_out_valid_login():
    client = TestClient(create_app(production_settings()))
    for _ in range(60):
        assert client.get("/", auth=("viewer", "wrong")).status_code == 401
    assert client.get("/", auth=("viewer", "wrong")).status_code == 429
    assert client.get("/", auth=TEST_AUTH).status_code == 200


def test_active_upload_limit_releases_after_completion():
    async def run():
        started = asyncio.Event()
        release = asyncio.Event()

        async def endpoint(scope, receive, send):
            started.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        guard = DemoGuardMiddleware(endpoint, Settings(max_concurrent_uploads=1))
        scope = {"type": "http", "method": "POST", "path": "/api/papers", "headers": []}
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        first = asyncio.create_task(guard(scope, receive, send))
        await started.wait()
        await guard(scope, receive, send)
        assert messages[0]["status"] == 429
        release.set()
        await first
        assert guard.active_uploads == 0

    asyncio.run(run())
