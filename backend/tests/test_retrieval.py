import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from app import papers
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "DATA_DIR", tmp_path / "retrieval-data")
    return TestClient(app)


def make_pdf(title: str, text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 540, 760), text, fontsize=11)
    document.set_metadata({"title": title, "author": "TraceScholar"})
    payload = document.tobytes()
    document.close()
    return payload


def upload(client: TestClient, title: str, text: str):
    return client.post(
        "/api/papers",
        files={"file": (f"{title}.pdf", make_pdf(title, text), "application/pdf")},
    ).json()


def test_retrieval_returns_relevant_chunk_with_page_source(client):
    attention = upload(
        client,
        "Attention Paper",
        "1\nAttention Mechanism\nThe attention mechanism maps a query and key value pairs to an output. "
        "Scaled dot product attention computes relevance weights before combining values.",
    )
    upload(
        client,
        "Optimization Paper",
        "1\nOptimization\nGradient descent updates parameters using the loss derivative and learning rate.",
    )

    response = client.post(
        "/api/research/retrieve",
        json={"question": "How does the attention mechanism use query and key values?", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_candidates"] >= 2
    assert payload["items"]
    top = payload["items"][0]
    assert top["source"]["paper_id"] == attention["paper_id"]
    assert top["source"]["page_start"] == 1
    assert top["paper_title"] == "Attention Paper"
    assert "query" in top["text"].lower()
    assert top["score"] > 0


def test_retrieval_can_limit_search_to_selected_paper(client):
    first = upload(client, "First", "Evidence about transformers and attention heads in neural networks.")
    second = upload(client, "Second", "Different evidence about transformers and attention heads in a later study.")

    response = client.post(
        "/api/research/retrieve",
        json={
            "question": "transformers attention heads",
            "paper_ids": [second["paper_id"]],
            "limit": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["items"]
    assert {item["source"]["paper_id"] for item in response.json()["items"]} == {second["paper_id"]}
    assert first["paper_id"] != second["paper_id"]


def test_retrieval_returns_empty_when_evidence_is_missing(client):
    upload(client, "Biology", "A paper about protein folding and molecular structures.")

    response = client.post(
        "/api/research/retrieve",
        json={"question": "quantum error correction surface codes"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_retrieval_rejects_weak_partial_keyword_overlap(client):
    upload(
        client,
        "Vision Thresholds",
        "A classification threshold changes the error rate for a visual recognition system.",
    )

    response = client.post(
        "/api/research/retrieve",
        json={"question": "What is the quantum error correction threshold for surface codes?"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_retrieval_builds_chunks_for_legacy_papers_without_structure(client):
    paper = upload(
        client,
        "Legacy CLIP Paper",
        "CLIP performs zero-shot image classification by comparing image embeddings "
        "with text embeddings created from class-name prompts.",
    )
    paper_dir = papers._papers_dir() / paper["paper_id"]
    (paper_dir / "structure.json").unlink()

    response = client.post(
        "/api/research/retrieve",
        json={"question": "How does CLIP perform zero-shot image classification?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_candidates"] >= 1
    assert payload["items"]
    assert payload["items"][0]["source"]["paper_id"] == paper["paper_id"]


def test_retrieval_validates_question_and_limit(client):
    assert client.post("/api/research/retrieve", json={"question": "x"}).status_code == 422
    assert client.post("/api/research/retrieve", json={"question": "valid question", "limit": 20}).status_code == 422


@pytest.mark.parametrize("question", [
    "CLIP 如何进行零样本图像分类？",
    "CLIP 如何利用图像和文本进行分类？",
])
def test_chinese_question_retrieves_english_clip_evidence(client, question):
    paper = upload(
        client, "CLIP",
        "CLIP performs zero-shot image classification by comparing image embeddings "
        "with text embeddings created from class-name prompts.",
    )
    response = client.post("/api/research/retrieve", json={"question": question})
    assert response.status_code == 200
    assert response.json()["items"]
    assert response.json()["items"][0]["source"]["paper_id"] == paper["paper_id"]


def test_chinese_question_without_matching_evidence_does_not_fabricate_results(client):
    upload(client, "Protein", "Protein folding in biological structures.")
    response = client.post(
        "/api/research/retrieve",
        json={"question": "CLIP 如何进行零样本图像分类？"},
    )
    assert response.json()["items"] == []


def test_chinese_zero_shot_method_outranks_results_discussion(client):
    upload(
        client, "CLIP",
        "Zero-shot image classification results vary across tasks. CLIP classification results "
        "on complex tasks are mixed. To perform zero-shot classification, CLIP compares "
        "image and text embeddings with cosine similarity and selects the most probable pair.",
    )
    response = client.post(
        "/api/research/retrieve", json={"question": "CLIP 如何进行零样本图像分类？"},
    )
    assert response.json()["items"]
    assert "To perform zero-shot classification" in response.json()["items"][0]["text"]


def test_chinese_question_works_with_legacy_english_paper(client):
    paper = upload(
        client, "Legacy CLIP",
        "CLIP performs zero-shot image classification by comparing image embeddings "
        "with text embeddings from class-name prompts.",
    )
    (papers._papers_dir() / paper["paper_id"] / "structure.json").unlink()
    response = client.post(
        "/api/research/retrieve",
        json={"question": "CLIP 如何进行零样本图像分类？"},
    )
    assert response.status_code == 200
    assert response.json()["items"]
    assert response.json()["items"][0]["source"]["paper_id"] == paper["paper_id"]
