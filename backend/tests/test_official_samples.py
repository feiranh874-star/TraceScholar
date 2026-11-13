"""Optional regression tests for the organizer-provided PDF package."""

import json
import os
import re
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


def test_official_bilingual_retrieval_benchmark(client):
    dataset_path = Path(__file__).parent / "evaluation" / "transformer_v7_questions.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    upload_sample(client, "1706.03762v7.pdf")
    answerable = []
    answerable_top_one = []
    false_positives = []
    fact_coverage = []
    expected_facts = json.loads(
        (Path(__file__).parent / "evaluation" / "transformer_v7_evidence_facts.json").read_text(encoding="utf-8")
    )

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value.casefold())

    for case in cases:
        response = client.post(
            "/api/research/retrieve",
            json={"question": case["question"], "limit": 6},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        if not case["answerable"]:
            false_positives.append(case["id"] if items else None)
            continue
        target_pages = set(case["expected_pages"])
        answerable_top_one.append(bool(items and any(
            result["source"]["page_start"] <= page <= result["source"]["page_end"]
            for page in target_pages
            for result in items[:1]
        )))
        answerable.append(any(
            any(item["source"]["page_start"] <= page <= item["source"]["page_end"] for page in target_pages)
            for item in items[:3]
        ))
        fact_groups = expected_facts.get(case["id"], [])
        evidence = normalize(" ".join(item["text"] for item in items[:3]))
        if fact_groups:
            supported = sum(
                any(normalize(term) in evidence for term in alternatives)
                for alternatives in fact_groups
            )
            fact_coverage.append(supported / len(fact_groups))

    recall_at_3 = sum(answerable) / max(1, len(answerable))
    hit_at_1 = sum(answerable_top_one) / max(1, len(answerable_top_one))
    assert hit_at_1 >= 0.85, f"page hit@1 was {hit_at_1:.0%}"
    assert recall_at_3 >= 0.90, f"page recall@3 was {recall_at_3:.0%}"
    mean_fact_coverage = sum(fact_coverage) / max(1, len(fact_coverage))
    assert mean_fact_coverage >= 0.90, f"required fact support coverage@3 was {mean_fact_coverage:.0%}"
    assert not [case_id for case_id in false_positives if case_id]

    agent_response = client.post(
        "/api/research/agent",
        json={"question": "只检索原文：Transformer architecture", "limit": 3},
    )
    assert agent_response.status_code == 200
    assert agent_response.json()["route"] == "retrieve_only"
    assert agent_response.json()["items"]

