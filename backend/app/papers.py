"""PDF upload, page text extraction, and local paper metadata endpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf as fitz
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse


router = APIRouter(prefix="/api/papers", tags=["papers"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_configured_data_dir = Path(os.getenv("STORAGE_DIR", "data"))
DATA_DIR = _configured_data_dir if _configured_data_dir.is_absolute() else PROJECT_ROOT / _configured_data_dir
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 2000
MAX_EXTRACTED_CHARS = 20_000_000
MIN_PAGE_TEXT_CHARS = 40
UPLOAD_CHUNK_BYTES = 1024 * 1024
PDF_MAGIC = b"%PDF-"
_STORE_LOCK = threading.Lock()


def _papers_dir() -> Path:
    path = DATA_DIR / "papers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(filename: str | None) -> str:
    value = (filename or "paper.pdf").replace("\\", "/").split("/")[-1]
    value = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    if not value or value in {".", ".."}:
        return "paper.pdf"
    return value[:255]


def _read_metadata(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _find_duplicate(sha256: str) -> dict[str, Any] | None:
    for paper_dir in _papers_dir().iterdir():
        if not paper_dir.is_dir() or paper_dir.name.startswith("."):
            continue
        metadata_path = paper_dir / "metadata.json"
        metadata = _read_metadata(metadata_path)
        if metadata and metadata.get("sha256") == sha256:
            return metadata
    return None


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _public_paper(metadata: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "paper_id": metadata["paper_id"],
        "filename": metadata["filename"],
        "sha256": metadata["sha256"],
        "page_count": metadata["page_count"],
        "title": metadata.get("title"),
        "author": metadata.get("author"),
        "parse_status": metadata["parse_status"],
        "needs_ocr_pages": metadata["needs_ocr_pages"],
        "created_at": metadata["created_at"],
        "duplicate": duplicate,
        "warnings": metadata["warnings"],
    }


def _metadata_path(paper_id: uuid.UUID) -> Path:
    return _papers_dir() / str(paper_id) / "metadata.json"


def _load_paper(paper_id: uuid.UUID) -> dict[str, Any]:
    metadata = _read_metadata(_metadata_path(paper_id))
    if metadata is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return metadata


def _extract_pdf(source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        document = fitz.open(source)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="PDF is damaged or unreadable") from exc

    try:
        if document.needs_pass:
            raise HTTPException(status_code=400, detail="Password-protected PDFs are not supported")
        page_count = document.page_count
        if page_count == 0:
            raise HTTPException(status_code=400, detail="PDF contains no pages")
        if page_count > MAX_PDF_PAGES:
            raise HTTPException(status_code=413, detail=f"PDF exceeds the {MAX_PDF_PAGES}-page limit")

        metadata = document.metadata or {}
        pages: list[dict[str, Any]] = []
        total_chars = 0
        for page_index in range(page_count):
            text = document.load_page(page_index).get_text("text").strip()
            total_chars += len(text)
            if total_chars > MAX_EXTRACTED_CHARS:
                raise HTTPException(status_code=413, detail="PDF expands to too much extracted text")
            pages.append(
                {
                    "page": page_index + 1,
                    "text": text,
                    "char_count": len(text),
                    "needs_ocr": len(text) < MIN_PAGE_TEXT_CHARS,
                    "bbox": None,
                }
            )

        extracted_metadata = {
            "page_count": page_count,
            "title": (metadata.get("title") or "").strip() or None,
            "author": (metadata.get("author") or "").strip() or None,
        }
        return extracted_metadata, pages
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="PDF is damaged or unreadable") from exc
    finally:
        document.close()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "An identical PDF already exists"}},
)
def upload_paper(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a PDF and persist extracted page text with 1-based page numbers."""

    papers_dir = _papers_dir()
    staging_dir = Path(tempfile.mkdtemp(prefix=".upload-", dir=papers_dir))
    temp_pdf = staging_dir / "upload.part"
    digest = hashlib.sha256()
    total_bytes = 0
    first_chunk = b""

    try:
        with temp_pdf.open("wb") as output:
            while chunk := file.file.read(UPLOAD_CHUNK_BYTES):
                if not first_chunk:
                    first_chunk = chunk[: len(PDF_MAGIC)]
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 50 MiB upload limit")
                digest.update(chunk)
                output.write(chunk)

        if total_bytes == 0 or first_chunk != PDF_MAGIC:
            raise HTTPException(status_code=400, detail="Uploaded file is not a PDF")

        sha256 = digest.hexdigest()
        with _STORE_LOCK:
            duplicate = _find_duplicate(sha256)
            if duplicate:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content=_public_paper(duplicate, duplicate=True),
                )

            extracted, pages = _extract_pdf(temp_pdf)
            paper_id = uuid.uuid4()
            filename = _safe_filename(file.filename)
            needs_ocr_pages = [page["page"] for page in pages if page["needs_ocr"]]
            warnings = []
            if needs_ocr_pages:
                warnings.append(f"{len(needs_ocr_pages)} page(s) have little or no text and may need OCR")
            if not extracted["title"]:
                warnings.append("PDF metadata does not include a title")

            parse_status = "needs_ocr" if needs_ocr_pages else "ready"
            metadata = {
                "paper_id": str(paper_id),
                "filename": filename,
                "sha256": sha256,
                **extracted,
                "parse_status": parse_status,
                "needs_ocr_pages": needs_ocr_pages,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "warnings": warnings,
            }

            page_dir = staging_dir / "pages"
            page_dir.mkdir()
            for page in pages:
                _write_json(page_dir / f"{page['page']:06d}.json", page)
            _write_json(staging_dir / "metadata.json", metadata)
            os.replace(temp_pdf, staging_dir / "source.pdf")
            destination = papers_dir / str(paper_id)
            os.replace(staging_dir, destination)
            return _public_paper(metadata)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not store uploaded PDF") from exc
    finally:
        file.file.close()
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


@router.get("")
def list_papers(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    papers: list[dict[str, Any]] = []
    for metadata_path in _papers_dir().glob("*/metadata.json"):
        metadata = _read_metadata(metadata_path)
        if metadata:
            papers.append(_public_paper(metadata))
    papers.sort(key=lambda item: item["created_at"], reverse=True)
    return {"items": papers[offset : offset + limit], "total": len(papers)}


@router.get("/{paper_id}")
def get_paper(paper_id: uuid.UUID) -> dict[str, Any]:
    return _public_paper(_load_paper(paper_id))


@router.get("/{paper_id}/pages/{page_number}")
def get_paper_page(paper_id: uuid.UUID, page_number: int) -> dict[str, Any]:
    metadata = _load_paper(paper_id)
    if page_number < 1 or page_number > metadata["page_count"]:
        raise HTTPException(status_code=404, detail="Page not found")
    page_path = _papers_dir() / str(paper_id) / "pages" / f"{page_number:06d}.json"
    page = _read_metadata(page_path)
    if page is None:
        raise HTTPException(status_code=404, detail="Page text not found")
    return page
