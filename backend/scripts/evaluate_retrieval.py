"""Run the small bilingual retrieval benchmark against the official PDF."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import papers  # noqa: E402
from app.main import app  # noqa: E402


DATASET_PATH = BACKEND_DIR / "tests" / "evaluation" / "transformer_v7_questions.json"
SAMPLE_FILENAME = "1706.03762v7.pdf"


def page_hit(item: dict, expected_pages: set[int]) -> bool:
    source = item.get("source") or {}
    page_start = int(source.get("page_start") or 0)
    page_end = int(source.get("page_end") or page_start)
    return any(page_start <= page <= page_end for page in expected_pages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", action="store_true", help="include per-question retrieval results")
    args = parser.parse_args()
    sample_dir_value = os.getenv("TRACESCHOLAR_SAMPLE_DIR")
    if not sample_dir_value:
        raise SystemExit("请先设置 TRACESCHOLAR_SAMPLE_DIR 为组委会 PDF 目录。")
    sample_path = Path(sample_dir_value) / SAMPLE_FILENAME
    if not sample_path.is_file():
        raise SystemExit(f"找不到官方样例：{sample_path}")

    questions = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    original_data_dir = papers.DATA_DIR
    with tempfile.TemporaryDirectory(prefix="tracescholar-eval-") as temp_dir:
        papers.DATA_DIR = Path(temp_dir)
        try:
            with TestClient(app) as client:
                with sample_path.open("rb") as stream:
                    response = client.post(
                        "/api/papers",
                        files={"file": (SAMPLE_FILENAME, stream, "application/pdf")},
                    )
                response.raise_for_status()

                rows = []
                for case in questions:
                    result = client.post(
                        "/api/research/retrieve",
                        json={"question": case["question"], "limit": 6},
                    )
                    result.raise_for_status()
                    items = result.json()["items"]
                    targets = set(case["expected_pages"])
                    row = {
                        "id": case["id"],
                        "question": case["question"],
                        "language": case["language"],
                        "answerable": case["answerable"],
                        "expected_pages": sorted(targets),
                        "top_results": [
                            {
                                "page_start": item["source"]["page_start"],
                                "page_end": item["source"]["page_end"],
                                "score": item["score"],
                                "text": item["text"][:180].replace("\n", " "),
                            }
                            for item in items[:3]
                        ],
                    }
                    if case["answerable"]:
                        row["hit_at_1"] = bool(items and page_hit(items[0], targets))
                        row["hit_at_3"] = any(page_hit(item, targets) for item in items[:3])
                        row["hit_at_5"] = any(page_hit(item, targets) for item in items[:5])
                    else:
                        row["false_positive"] = bool(items)
                    rows.append(row)

                answerable_rows = [row for row in rows if row["answerable"]]
                negative_rows = [row for row in rows if not row["answerable"]]
                denominator = max(1, len(answerable_rows))
                metrics = {
                    "questions": len(rows),
                    "answerable_questions": len(answerable_rows),
                    "unanswerable_questions": len(negative_rows),
                    "page_hit_at_1": round(sum(row["hit_at_1"] for row in answerable_rows) / denominator, 4),
                    "page_recall_at_3": round(sum(row["hit_at_3"] for row in answerable_rows) / denominator, 4),
                    "page_recall_at_5": round(sum(row["hit_at_5"] for row in answerable_rows) / denominator, 4),
                    "unanswerable_false_positive_rate": round(
                        sum(row["false_positive"] for row in negative_rows) / max(1, len(negative_rows)), 4
                    ),
                }
                compact_rows = [
                    {
                        "id": row["id"],
                        "expected_pages": row["expected_pages"],
                        "returned_pages": sorted({
                            page
                            for item in row["top_results"]
                            for page in range(item["page_start"], item["page_end"] + 1)
                        }),
                        "hit_at_1": row.get("hit_at_1"),
                        "hit_at_3": row.get("hit_at_3"),
                        "false_positive": row.get("false_positive"),
                    }
                    for row in rows
                ]
                report = {"metrics": metrics}
                if args.details:
                    report["cases"] = compact_rows
                else:
                    report["page_misses_at_1"] = [row["id"] for row in compact_rows if row.get("hit_at_1") is False]
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0
        finally:
            papers.DATA_DIR = original_data_dir


if __name__ == "__main__":
    raise SystemExit(main())
