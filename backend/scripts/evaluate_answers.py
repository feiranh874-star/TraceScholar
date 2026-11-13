"""Run a small, explicitly bounded DeepSeek answer-quality check."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import papers  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import app  # noqa: E402


SAMPLE_FILENAME = "1706.03762v7.pdf"
CASES_PATH = BACKEND_DIR / "tests" / "evaluation" / "answer_quality_cases.json"


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value.casefold())


def load_settings() -> Settings:
    env_file = BACKEND_DIR.parent / ".env"
    values = dotenv_values(env_file) if env_file.is_file() else {}
    api_key = os.getenv("LLM_API_KEY") or values.get("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or values.get("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL") or values.get("LLM_MODEL")
    if not all((api_key, base_url, model)):
        raise SystemExit("本地模型配置不完整；请在项目 .env 中配置 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL 后重试。")
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER") or values.get("LLM_PROVIDER") or "deepseek",
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_model=model,
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS") or values.get("LLM_TIMEOUT_SECONDS") or 45),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answerable-limit", type=int, default=6, choices=range(1, 7), metavar="1-6")
    parser.add_argument("--case-ids", nargs="+", help="evaluate only the listed case ids")
    args = parser.parse_args()
    sample_dir_value = os.getenv("TRACESCHOLAR_SAMPLE_DIR")
    if not sample_dir_value:
        raise SystemExit("请先设置 TRACESCHOLAR_SAMPLE_DIR 为组委会 PDF 目录。")
    sample_path = Path(sample_dir_value) / SAMPLE_FILENAME
    if not sample_path.is_file():
        raise SystemExit(f"找不到官方样例：{sample_path}")

    settings = load_settings()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    answerable = [case for case in cases if case["answerable"]]
    unanswerable = [case for case in cases if not case["answerable"]]
    if args.case_ids:
        requested_ids = set(args.case_ids)
        cases = [case for case in cases if case["id"] in requested_ids]
        unknown_ids = requested_ids - {case["id"] for case in cases}
        if unknown_ids:
            raise SystemExit(f"未找到评测题 ID：{', '.join(sorted(unknown_ids))}")
    else:
        cases = answerable[: args.answerable_limit] + unanswerable
    original_data_dir = papers.DATA_DIR
    original_settings = app.state.settings
    rows = []
    with tempfile.TemporaryDirectory(prefix="tracescholar-answer-eval-") as temp_dir:
        papers.DATA_DIR = Path(temp_dir)
        app.state.settings = settings
        try:
            with TestClient(app) as client:
                with sample_path.open("rb") as stream:
                    upload = client.post(
                        "/api/papers",
                        files={("file"): (SAMPLE_FILENAME, stream, "application/pdf")},
                    )
                upload.raise_for_status()

                for case in cases:
                    response = client.post(
                        "/api/research/agent",
                        json={"question": case["question"], "limit": 6},
                    )
                    row = {"id": case["id"], "answerable": case["answerable"], "status_code": response.status_code}
                    if response.status_code != 200:
                        row["error"] = response.json().get("detail", "请求失败")
                        rows.append(row)
                        continue

                    payload = response.json()
                    if not case["answerable"]:
                        row["correct_refusal"] = bool(payload["insufficient"] and not payload["citations"])
                        rows.append(row)
                        continue

                    answer = normalized(payload.get("answer") or "")
                    fact_groups = case["fact_groups"]
                    matched_facts = sum(
                        any(normalized(phrase) in answer for phrase in alternatives)
                        for alternatives in fact_groups
                    )
                    expected_pages = set(case["expected_pages"])
                    citation_pages = {
                        page
                        for citation in payload.get("citations", [])
                        for page in range(
                            citation["source"]["page_start"],
                            citation["source"]["page_end"] + 1,
                        )
                    }
                    row["cited_expected_page"] = bool(citation_pages & expected_pages)
                    row["fact_coverage"] = matched_facts / max(1, len(fact_groups))
                    row["all_fact_groups_covered"] = matched_facts == len(fact_groups)
                    row["missing_fact_groups"] = [
                        alternatives[0]
                        for alternatives in fact_groups
                        if not any(normalized(phrase) in answer for phrase in alternatives)
                    ]
                    row["has_valid_citation"] = bool(payload.get("citations"))
                    rows.append(row)
        finally:
            papers.DATA_DIR = original_data_dir
            app.state.settings = original_settings

    answerable = [row for row in rows if row["answerable"] and "fact_coverage" in row]
    unanswerable = [row for row in rows if not row["answerable"]]
    failed = [row for row in rows if row.get("status_code") != 200]
    report = {
        "model": settings.llm_model,
        "cases": len(rows),
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "citation_valid_rate": round(sum(row["has_valid_citation"] for row in answerable) / max(1, len(answerable)), 4),
        "expected_page_citation_rate": round(sum(row["cited_expected_page"] for row in answerable) / max(1, len(answerable)), 4),
        "reference_fact_coverage": round(sum(row["fact_coverage"] for row in answerable) / max(1, len(answerable)), 4),
        "all_reference_facts_covered_rate": round(sum(row["all_fact_groups_covered"] for row in answerable) / max(1, len(answerable)), 4),
        "unanswerable_refusal_rate": round(sum(row.get("correct_refusal", False) for row in unanswerable) / max(1, len(unanswerable)), 4),
        "failed_cases": failed,
        "per_case": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
