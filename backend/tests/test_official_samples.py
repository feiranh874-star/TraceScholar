"""Optional regression tests for the organizer-provided PDF package."""

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import papers
from app import research
from app.config import Settings
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


def upload_sample(client: TestClient, filename: str, **fields):
    sample = SAMPLE_DIR / filename
    assert sample.is_file(), f"Missing organizer sample: {filename}"
    with sample.open("rb") as stream:
        return client.post(
            "/api/papers",
            files={"file": (sample.name, stream, "application/pdf")},
            data=fields,
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


def test_ppo_comma_separated_author_header(client):
    response=upload_sample(client,'1707.06347v2.pdf')
    assert response.status_code==201,response.text
    assert response.json()['authors']==['John Schulman','Filip Wolski','Prafulla Dhariwal','Alec Radford','Oleg Klimov']


def test_scan_still_prompts_version_conflict_before_ocr(client):
    latest = upload_sample(client, '1706.03762v7.pdf').json()
    response = upload_sample(client, '1706.03762v1_img.pdf', conflict_action='ask')
    assert response.status_code == 409
    conflict = response.json()
    assert conflict['recommendation'] == 'keep_existing_newer'
    assert conflict['matches'][0]['paper']['paper_id'] == latest['paper_id']
    assert client.get('/api/papers').json()['total'] == 1
    kept = upload_sample(client, '1706.03762v1_img.pdf', conflict_action='keep_both')
    assert kept.status_code == 201
    assert kept.json()['work_id'] == latest['work_id']
    assert kept.json()['needs_ocr_pages'] == list(range(1, 16))


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


def test_official_multidocument_retrieval_and_comparison(client, monkeypatch):
    dataset_path = Path(__file__).parent / "evaluation" / "official_multidoc_questions.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    paper_ids = {}
    for filename in dataset["samples"]:
        response = upload_sample(client, filename)
        assert response.status_code == 201
        paper_ids[filename] = response.json()["paper_id"]

    monkeypatch.setattr(client.app.state, "settings", Settings(
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="test-only-key",
        llm_model="deepseek-flash",
    ))

    def mocked_comparison(_question, evidence, **_kwargs):
        citations = [f"[E{index}]" for index in range(1, len(evidence) + 1)]
        return "所选来源的原文信息分别如下。" + " ".join(citations)

    monkeypatch.setattr(research, "generate_grounded_answer", mocked_comparison)
    page_hits = []
    global_page_hits = []
    fact_coverage = []
    comparison_source_checks = []
    page_misses = []

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value.casefold())

    for case in dataset["cases"]:
        expected_sources = case["expected_sources"]
        source_ids = [paper_ids[filename] for filename in expected_sources]
        is_comparison = case["id"].startswith("cross")
        if is_comparison:
            response = client.post(
                "/api/research/compare",
                json={"question": case["question"], "paper_ids": source_ids, "limit": 10},
            )
        else:
            response = client.post(
                "/api/research/retrieve",
                json={"question": case["question"], "paper_ids": source_ids, "limit": 6},
            )
        assert response.status_code == 200, f"{case['id']}: {response.text}"
        payload = response.json()
        items = payload["items"]
        if is_comparison:
            assert payload["insufficient"] is False
            cited_papers = {item["source"]["paper_id"] for item in payload["citations"]}
            comparison_source_checks.append(set(source_ids).issubset(cited_papers))
        else:
            global_response = client.post(
                "/api/research/retrieve",
                json={"question": case["question"], "paper_ids": [], "limit": 6},
            )
            assert global_response.status_code == 200, f"{case['id']}: {global_response.text}"
            global_items = global_response.json()["items"]
            filename, expected_pages = next(iter(expected_sources.items()))
            expected_id = paper_ids[filename]
            global_source_items = [item for item in global_items if item["source"]["paper_id"] == expected_id]
            global_page_hits.append(any(
                item["source"]["page_start"] <= page <= item["source"]["page_end"]
                for item in global_source_items
                for page in expected_pages
            ))

        for filename, expected_pages in expected_sources.items():
            expected_id = paper_ids[filename]
            source_items = [item for item in items if item["source"]["paper_id"] == expected_id]
            page_hit = any(
                item["source"]["page_start"] <= page <= item["source"]["page_end"]
                for item in source_items[:6]
                for page in expected_pages
            )
            page_hits.append(page_hit)
            if not page_hit:
                page_misses.append((case["id"], filename, expected_pages))
            groups = case.get("fact_groups_by_source", {}).get(filename)
            if groups is None and len(expected_sources) == 1:
                groups = case.get("fact_groups", [])
            if groups:
                evidence = normalize(" ".join(item["text"] for item in source_items[:6]))
                supported = sum(
                    any(normalize(phrase) in evidence for phrase in alternatives)
                    for alternatives in groups
                )
                fact_coverage.append(supported / len(groups))

    page_recall = sum(page_hits) / max(1, len(page_hits))
    global_page_recall = sum(global_page_hits) / max(1, len(global_page_hits))
    mean_fact_coverage = sum(fact_coverage) / max(1, len(fact_coverage))
    assert page_recall >= 0.80, f"paper-scoped official page recall@6 was {page_recall:.0%}; misses={page_misses}"
    assert global_page_recall >= 0.50, f"all-library page recall@6 was {global_page_recall:.0%}"
    assert mean_fact_coverage >= 0.70, f"official corpus evidence fact coverage@6 was {mean_fact_coverage:.0%}"
    assert comparison_source_checks and all(comparison_source_checks)

