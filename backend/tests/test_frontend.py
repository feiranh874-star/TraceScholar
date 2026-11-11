from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_home_serves_chinese_workspace():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "科研工作台" in response.text
    assert "可信科研助手" in response.text


def test_frontend_assets_are_available():
    stylesheet = client.get("/assets/app.css")
    script = client.get("/assets/app.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]


def test_developer_docs_remain_available():
    docs = client.get("/docs")
    openapi = client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200
    assert "/" not in openapi.json()["paths"]
    assert "/api/papers" in openapi.json()["paths"]


def test_unknown_api_path_keeps_json_404():
    response = client.get("/api/not-found")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}
