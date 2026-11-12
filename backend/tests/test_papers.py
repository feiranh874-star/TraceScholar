from concurrent.futures import ThreadPoolExecutor

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from app import papers
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "data")
    return TestClient(app)


def make_pdf(*page_texts: str) -> bytes:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    document.set_metadata({"title": "Test Paper", "author": "TraceScholar"})
    payload = document.tobytes()
    document.close()
    return payload


def test_upload_persists_per_page_text_and_metadata(client):
    payload = make_pdf("This is a sufficiently long first page for extraction.", "Second page has enough text for extraction.")
    response = client.post("/api/papers", files={"file": ("paper.pdf", payload, "application/pdf")})

    assert response.status_code == 201
    paper = response.json()
    assert paper["page_count"] == 2
    assert paper["title"] == "Test Paper"
    assert paper["parse_status"] == "ready"
    assert paper["duplicate"] is False

    page_response = client.get(f"/api/papers/{paper['paper_id']}/pages/2")
    assert page_response.status_code == 200
    assert page_response.json()["page"] == 2
    assert "Second page" in page_response.json()["text"]

    detail = client.get(f"/api/papers/{paper['paper_id']}")
    assert detail.status_code == 200
    assert detail.json()["sha256"] == paper["sha256"]


def test_duplicate_pdf_returns_existing_record(client):
    payload = make_pdf("A page with enough readable content to avoid OCR detection.")
    def upload(filename):
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(
                "/api/papers",
                files={"file": (filename, payload, "application/pdf")},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(upload, ("first.pdf", "renamed.pdf"))

    assert {first.status_code, second.status_code} == {200, 201}
    assert second.json()["paper_id"] == first.json()["paper_id"]
    duplicate_response = first if first.status_code == 200 else second
    assert duplicate_response.json()["duplicate"] is True
    assert len(client.get("/api/papers").json()["items"]) == 1


def test_arxiv_versions_share_work_and_report_newer_existing_version(client):
    version_7 = make_pdf("A newer version with enough readable content for extraction.")
    version_1 = make_pdf("An older version with different readable content for extraction.")

    latest = client.post(
        "/api/papers",
        files={"file": ("1706.03762v7.pdf", version_7, "application/pdf")},
    ).json()
    older = client.post(
        "/api/papers",
        files={"file": ("1706.03762v1.pdf", version_1, "application/pdf")},
    ).json()

    assert latest["arxiv_id"] == "1706.03762"
    assert latest["version_label"] == "v7"
    assert older["version_label"] == "v1"
    assert older["work_id"] == latest["work_id"]
    assert older["version_relation"] == {
        "kind": "older_version",
        "related_count": 1,
        "latest_paper_id": latest["paper_id"],
        "latest_version_label": "v7",
        "recommendation": "keep_existing_newer",
    }
    assert client.get("/api/papers").json()["total"] == 2


def test_structure_and_chunks_preserve_evidence_source(client):
    payload = make_pdf(
        "Abstract\nThis abstract contains enough text to be indexed.\n"
        "1\nIntroduction\nThis introduction explains the tested document structure in detail."
    )
    paper = client.post(
        "/api/papers",
        files={"file": ("2401.12345v2.pdf", payload, "application/pdf")},
    ).json()

    structure = client.get(f"/api/papers/{paper['paper_id']}/structure").json()
    chunks = client.get(f"/api/papers/{paper['paper_id']}/chunks").json()

    assert structure["section_count"] >= 2
    assert {section["title"] for section in structure["sections"]} >= {"Abstract", "Introduction"}
    assert chunks["total"] >= 2
    section_titles = {section["section_id"]: section["title"] for section in structure["sections"]}
    chunk_sections = {section_titles[item["source"]["section_id"]] for item in chunks["items"]}
    assert chunk_sections >= {"Abstract", "Introduction"}
    source = chunks["items"][0]["source"]
    assert source["paper_id"] == paper["paper_id"]
    assert source["work_id"] == paper["work_id"]
    assert source["version_label"] == "v2"
    assert source["page_start"] == 1


def test_non_pdf_and_corrupt_pdf_are_rejected_without_persisting(client):
    non_pdf = client.post("/api/papers", files={"file": ("notes.pdf", b"not a pdf", "application/pdf")})
    corrupt_pdf = client.post("/api/papers", files={"file": ("broken.pdf", b"%PDF-1.4 broken", "application/pdf")})

    assert non_pdf.status_code == 400
    assert corrupt_pdf.status_code == 400
    assert client.get("/api/papers").json()["total"] == 0
    assert not list((papers.DATA_DIR / "papers").glob(".upload-*"))


def test_oversized_upload_is_rejected(client, monkeypatch):
    monkeypatch.setattr(papers, "MAX_UPLOAD_BYTES", 10)
    payload = b"%PDF-1.4" + b"x" * 10
    response = client.post("/api/papers", files={"file": ("large.pdf", payload, "application/pdf")})

    assert response.status_code == 413
    assert client.get("/api/papers").json()["total"] == 0


def test_empty_text_page_is_marked_for_ocr(client):
    payload = make_pdf("")
    response = client.post("/api/papers", files={"file": ("scan.pdf", payload, "application/pdf")})

    assert response.status_code == 201
    paper = response.json()
    assert paper["parse_status"] == "needs_ocr"
    assert paper["needs_ocr_pages"] == [1]
    assert client.get(f"/api/papers/{paper['paper_id']}/pages/1").json()["text"] == ""


def test_storage_quota_rejects_upload_and_cleans_staging(client, monkeypatch):
    monkeypatch.setattr(papers, "MAX_STORAGE_BYTES", 1)
    payload = make_pdf("A sufficiently long page for the storage quota regression test.")
    response = client.post("/api/papers", files={"file": ("paper.pdf", payload, "application/pdf")})
    assert response.status_code == 507
    assert client.get("/api/papers").json()["total"] == 0
    assert not list((papers.DATA_DIR / "papers").glob(".upload-*"))


def test_filename_cannot_control_storage_path(client):
    payload = make_pdf("A valid page containing enough text for the upload parser.")
    response = client.post("/api/papers", files={"file": ("../../outside.pdf", payload, "application/pdf")})

    assert response.status_code == 201
    assert response.json()["filename"] == "outside.pdf"
    assert (papers.DATA_DIR / "papers" / response.json()["paper_id"] / "source.pdf").exists()


def test_page_limit_is_enforced(client, monkeypatch):
    monkeypatch.setattr(papers, "MAX_PDF_PAGES", 1)
    payload = make_pdf("Page one has enough text for extraction.", "Page two has enough text for extraction.")
    response = client.post("/api/papers", files={"file": ("many-pages.pdf", payload, "application/pdf")})

    assert response.status_code == 413
    assert client.get("/api/papers").json()["total"] == 0


def test_extracted_text_limit_is_enforced(client, monkeypatch):
    monkeypatch.setattr(papers, "MAX_EXTRACTED_CHARS", 12)
    payload = make_pdf("This page contains far more than twelve extracted characters.")
    response = client.post("/api/papers", files={"file": ("large-text.pdf", payload, "application/pdf")})

    assert response.status_code == 413
    assert client.get("/api/papers").json()["total"] == 0


def test_password_protected_pdf_is_rejected(client):
    document = fitz.open()
    document.new_page().insert_text((72, 72), "Protected paper content")
    payload = document.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()

    response = client.post("/api/papers", files={"file": ("locked.pdf", payload, "application/pdf")})

    assert response.status_code == 400
    assert "Password-protected" in response.json()["detail"]
    assert client.get("/api/papers").json()["total"] == 0
