"""Optional regression tests for the organizer-provided PDF package."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import papers
from app.main import app


SAMPLE_DIR_VALUE = os.getenv("TRACESCHOLAR_SAMPLE_DIR")
SAMPLE_DIR = Path(SAMPLE_DIR_VALUE) if SAMPLE_DIR_VALUE else None
pytestmark = pytest.mark.skipif(
    SAMPLE_DIR is None or not SAMPLE_DIR.is_dir(),
    reason="Set TRACESCHOLAR_SAMPLE_DIR to the organizer PDF directory",
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "official-data")
    return TestClient(app)


def upload_sample(client: TestClient, filename: str):
    sample = SAMPLE_DIR / filename
    assert sample.is_file(), f"Missing organizer sample: {filename}"
    with sample.open("rb") as stream:
        return client.post(
            "/api/papers",
            files={"file": (sample.name, stream, "application/pdf")},
        )


def test_attention_versions_are_grouped_and_structured(client):
    version_7_response = upload_sample(client, "1706.03762v7.pdf")
    version_1_response = upload_sample(client, "1706.03762v1.pdf")

    assert version_7_response.status_code == 201
    assert version_1_response.status_code == 201
    version_7 = version_7_response.json()
    version_1 = version_1_response.json()
    assert version_7["title"] == "Attention Is All You Need"
    assert len(version_7["authors"]) == 8
    assert version_7["abstract"]
    assert version_7["section_count"] >= 10
    assert version_7["chunk_count"] >= 15
    assert version_7["work_id"] == version_1["work_id"]
    assert version_1["version_relation"]["kind"] == "older_version"
    assert version_1["version_relation"]["latest_version_label"] == "v7"

    structure = client.get(f"/api/papers/{version_7['paper_id']}/structure").json()
    assert any(section["title"] == "Introduction" for section in structure["sections"])


def test_image_only_version_is_marked_for_ocr(client):
    response = upload_sample(client, "1706.03762v1_img.pdf")

    assert response.status_code == 201
    paper = response.json()
    assert paper["arxiv_id"] == "1706.03762"
    assert paper["version_label"] == "v1"
    assert paper["parse_status"] == "needs_ocr"
    assert len(paper["needs_ocr_pages"]) == paper["page_count"] == 15
    assert paper["chunk_count"] == 0


def test_long_book_parses_all_pages(client):
    response = upload_sample(client, "UnderstandingDeepLearning_02_09_26_C.pdf")

    assert response.status_code == 201
    paper = response.json()
    assert paper["page_count"] == 541
    assert paper["chunk_count"] >= 500

