"""Run the bounded multi-document benchmark without external model calls."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import papers, research  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import app  # noqa: E402


DATASET_PATH = BACKEND_DIR / "tests" / "evaluation" / "official_multidoc_questions.json"


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value.casefold())


def main() -> int:
    sample_dir_value = os.getenv("TRACESCHOLAR_SAMPLE_DIR")
    if not sample_dir_value:
        raise SystemExit("请先设置 TRACESCHOLAR_SAMPLE_DIR 为组委会 PDF 目录。")
    sample_dir = Path(sample_dir_value)
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    for filename in dataset["samples"]:
        if not (sample_dir / filename).is_file():
            raise SystemExit(f"找不到官方样例：{sample_dir / filename}")

    original_data_dir = papers.DATA_DIR
    original_settings = app.state.settings
    original_generator = research.generate_grounded_answer
    paper_ids: dict[str, str] = {}
    page_hits: list[bool] = []
    global_page_hits: list[bool] = []
    fact_hits: list[bool] = []
    comparison_checks: list[bool] = []

    def mocked_comparison(_question, evidence, **_kwargs):
        return "逐篇证据对照。" + " ".join(f"[E{index}]" for index in range(1, len(evidence) + 1))

    with tempfile.TemporaryDirectory(prefix="tracescholar-official-corpus-") as temp_dir:
        papers.DATA_DIR = Path(temp_dir)
        app.state.settings = Settings(
            llm_provider="offline-evaluation",
            llm_base_url="https://example.invalid/v1",
            llm_api_key="offline-evaluation-key",
            llm_model="offline-evaluation",
        )
        research.generate_grounded_answer = mocked_comparison
        try:
            with TestClient(app) as client:
                for filename in dataset["samples"]:
                    with (sample_dir / filename).open("rb") as stream:
                        response = client.post(
                            "/api/papers",
                            files={"file": (filename, stream, "application/pdf")},
                        )
                    response.raise_for_status()
                    paper_ids[filename] = response.json()["paper_id"]

                for case in dataset["cases"]:
                    expected_sources = case["expected_sources"]
                    selected_ids = [paper_ids[filename] for filename in expected_sources]
                    is_comparison = case["id"].startswith("cross")
                    if is_comparison:
                        response = client.post(
                            "/api/research/compare",
                            json={"question": case["question"], "paper_ids": selected_ids, "limit": 10},
                        )
                    else:
                        response = client.post(
                            "/api/research/retrieve",
                            json={"question": case["question"], "paper_ids": selected_ids, "limit": 6},
                        )
                    response.raise_for_status()
                    payload = response.json()
                    items = payload["items"]
                    if is_comparison:
                        cited_papers = {item["source"]["paper_id"] for item in payload["citations"]}
                        comparison_checks.append(set(selected_ids).issubset(cited_papers))
                    else:
                        global_payload = client.post(
                            "/api/research/retrieve",
                            json={"question": case["question"], "paper_ids": [], "limit": 6},
                        ).json()
                        filename, expected_pages = next(iter(expected_sources.items()))
                        expected_id = paper_ids[filename]
                        scoped = [item for item in global_payload["items"] if item["source"]["paper_id"] == expected_id]
                        global_page_hits.append(any(
                            item["source"]["page_start"] <= page <= item["source"]["page_end"]
                            for item in scoped
                            for page in expected_pages
                        ))

                    for filename, expected_pages in expected_sources.items():
                        expected_id = paper_ids[filename]
                        scoped = [item for item in items if item["source"]["paper_id"] == expected_id]
                        page_hits.append(any(
                            item["source"]["page_start"] <= page <= item["source"]["page_end"]
                            for item in scoped[:6]
                            for page in expected_pages
                        ))
                        groups = case.get("fact_groups_by_source", {}).get(filename)
                        if groups is None and len(expected_sources) == 1:
                            groups = case.get("fact_groups", [])
                        if groups:
                            evidence = normalize(" ".join(item["text"] for item in scoped[:6]))
                            fact_hits.extend(
                                any(normalize(term) in evidence for term in alternatives)
                                for alternatives in groups
                            )
        finally:
            papers.DATA_DIR = original_data_dir
            app.state.settings = original_settings
            research.generate_grounded_answer = original_generator

    report = {
        "documents": len(dataset["samples"]),
        "questions": len(dataset["cases"]),
        "paper_scoped_page_hit_at_6": round(sum(page_hits) / max(1, len(page_hits)), 4),
        "all_library_page_hit_at_6": round(sum(global_page_hits) / max(1, len(global_page_hits)), 4),
        "evidence_fact_coverage_at_6": round(sum(fact_hits) / max(1, len(fact_hits)), 4),
        "comparison_source_coverage": round(sum(comparison_checks) / max(1, len(comparison_checks)), 4),
        "paper_scoped_checks": len(page_hits),
        "all_library_checks": len(global_page_hits),
        "evidence_fact_checks": len(fact_hits),
        "comparison_checks": len(comparison_checks),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
