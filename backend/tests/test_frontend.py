from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_home_serves_chinese_workspace():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "科研工作台" in response.text
    assert "可信科研助手" in response.text
    assert "证据检索" in response.text
    assert "researchForm" in response.text
    assert "researchAnswer" in response.text
    assert "answerResult" in response.text
    assert "查看助手执行步骤" in response.text
    assert "智能体回答" in response.text
    assert "多篇比较" in response.text
    assert "researchCompare" in response.text


def test_frontend_assets_are_available():
    stylesheet = client.get("/assets/app.css")
    script = client.get("/assets/app.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "/api/research/agent" in script.text


def test_developer_docs_remain_available():
    docs = client.get("/docs")
    openapi = client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200
    assert "/" not in openapi.json()["paths"]
    assert "/api/papers" in openapi.json()["paths"]
    assert "/api/research/retrieve" in openapi.json()["paths"]
    assert "/api/research/answer" in openapi.json()["paths"]
    assert "/api/research/agent" in openapi.json()["paths"]
    assert "/api/research/compare" in openapi.json()["paths"]


def test_unknown_api_path_keeps_json_404():
    response = client.get("/api/not-found")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_reader_has_dedicated_refreshable_page_and_assets():
    response = client.get('/reader/00000000-0000-0000-0000-000000000001?page=4')
    assert response.status_code == 200
    assert '适应整页' in response.text and '返回论文库' in response.text
    assert 'reader-canvas' in response.text and 'drawer-backdrop' not in response.text
    assert client.get('/assets/reader.js').status_code == 200
    assert client.get('/assets/reader.css').status_code == 200
    assert 'paperDrawer' not in client.get('/').text
    assert client.get('/reader/not-a-uuid').status_code == 422
