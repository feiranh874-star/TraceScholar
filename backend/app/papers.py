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
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response

from app.similarity import content_signature, overlap
from app.models import PageRecord, PaperMetadataRecord, SourceIdentifiers, VersionRelation
from app.processing import build_chunks, derive_work_id, extract_document_metadata, extract_sections


router = APIRouter(prefix="/api/papers", tags=["papers"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_configured_data_dir = Path(os.getenv("STORAGE_DIR", "data"))
DATA_DIR = _configured_data_dir if _configured_data_dir.is_absolute() else PROJECT_ROOT / _configured_data_dir
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_STORAGE_BYTES = int(os.getenv("MAX_STORAGE_BYTES", str(512 * 1024 * 1024)))
if MAX_STORAGE_BYTES < 1:
    raise ValueError("MAX_STORAGE_BYTES must be positive")
MAX_PDF_PAGES = 2000
MAX_EXTRACTED_CHARS = 20_000_000
MIN_PAGE_TEXT_CHARS = 40
UPLOAD_CHUNK_BYTES = 1024 * 1024
PDF_MAGIC = b"%PDF-"
_STORE_LOCK = threading.RLock()


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
        if metadata and not metadata.get("archived") and metadata.get("sha256") == sha256:
            return metadata
    return None


def _all_metadata() -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    for metadata_path in _papers_dir().glob("*/metadata.json"):
        if metadata_path.parent.name.startswith("."):
            continue
        metadata = _read_metadata(metadata_path)
        if metadata and not metadata.get("archived"):
            papers.append(metadata)
    return papers


def _storage_usage_bytes() -> int:
    total = 0
    for paper_dir in _papers_dir().iterdir():
        if not paper_dir.is_dir() or paper_dir.name.startswith(".") or paper_dir.is_symlink():
            continue
        total += sum(path.stat().st_size for path in paper_dir.rglob("*") if path.is_file() and not path.is_symlink())
    for folder in ('jobs', 'agent-runs'):
        total += sum(p.stat().st_size for p in (DATA_DIR/folder).glob('*') if p.is_file() and not p.is_symlink())
    return total


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _version_relation(metadata: dict[str, Any]) -> dict[str, Any]:
    work_id = metadata.get("work_id") or metadata["paper_id"]
    related = [
        candidate
        for candidate in _all_metadata()
        if (candidate.get("work_id") or candidate["paper_id"]) == work_id
        and candidate.get("paper_id") != metadata.get("paper_id")
    ]
    candidates = [metadata, *related]
    latest = max(
        candidates,
        key=lambda candidate: (
            candidate.get("version_number") or -1,
            candidate.get("created_at") or "",
        ),
    )
    current_version = metadata.get("version_number")
    latest_version = latest.get("version_number")

    if not related:
        kind = "none"
        recommendation = "none"
    elif current_version is None or latest_version is None:
        kind = "related"
        recommendation = "keep_both"
    elif current_version < latest_version:
        kind = "older_version"
        recommendation = "keep_existing_newer"
    elif any((candidate.get("version_number") or -1) < current_version for candidate in related):
        kind = "newer_version"
        recommendation = "keep_uploaded_newer"
    else:
        kind = "same_version"
        recommendation = "keep_both"

    return VersionRelation(
        kind=kind,
        related_count=len(related),
        latest_paper_id=latest["paper_id"],
        latest_version_label=latest.get("version_label"),
        recommendation=recommendation,
    ).model_dump(mode="json")


def _public_paper(metadata: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    identifiers = metadata.get("identifiers") or {}
    return {
        "paper_id": metadata["paper_id"],
        "work_id": metadata.get("work_id", metadata["paper_id"]),
        "filename": metadata["filename"],
        "sha256": metadata["sha256"],
        "page_count": metadata["page_count"],
        "title": metadata.get("title"),
        "author": metadata.get("author"),
        "authors": metadata.get("authors", []),
        "abstract": metadata.get("abstract"),
        "identifiers": identifiers,
        "arxiv_id": identifiers.get("arxiv_id"),
        "doi": identifiers.get("doi"),
        "version_label": metadata.get("version_label"),
        "version_number": metadata.get("version_number"),
        "parse_status": metadata["parse_status"],
        "needs_ocr_pages": metadata["needs_ocr_pages"],
        "section_count": metadata.get("section_count", 0),
        "chunk_count": metadata.get("chunk_count", 0),
        "created_at": metadata["created_at"],
        "duplicate": duplicate,
        "warnings": metadata["warnings"],
        "version_relation": _version_relation(metadata),
    }


def _metadata_path(paper_id: uuid.UUID) -> Path:
    return _papers_dir() / str(paper_id) / "metadata.json"


def _load_paper(paper_id: uuid.UUID) -> dict[str, Any]:
    metadata = _read_metadata(_metadata_path(paper_id))
    if metadata is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return metadata


def _extract_pdf(source: Path, filename: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
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

        pages: list[dict[str, Any]] = []
        total_chars = 0
        for page_index in range(page_count):
            text = document.load_page(page_index).get_text("text").strip()
            total_chars += len(text)
            if total_chars > MAX_EXTRACTED_CHARS:
                raise HTTPException(status_code=413, detail="PDF expands to too much extracted text")
            pages.append(
                PageRecord(
                    page=page_index + 1,
                    text=text,
                    char_count=len(text),
                    needs_ocr=len(text) < MIN_PAGE_TEXT_CHARS,
                    bbox=None,
                ).model_dump(mode="json")
            )

        extracted_metadata = {"page_count": page_count, **extract_document_metadata(document, pages, filename)}
        return extracted_metadata, pages, extract_sections(pages)
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
def upload_paper(
    file: UploadFile = File(...),
    conflict_action: str = Form(default="keep_both"),
    target_paper_id: str = Form(default=""),
    target_sha256: str = Form(default=""),
) -> dict[str, Any]:
    """Upload a PDF and persist extracted page text with 1-based page numbers."""

    if conflict_action not in {"ask", "keep_both", "replace"}:
        raise HTTPException(422, "Invalid conflict action")
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
        filename = _safe_filename(file.filename)
        from app import ocr,jobs
        with ocr._LOCK,jobs._LOCK,_STORE_LOCK:
            duplicate = _find_duplicate(sha256)
            if duplicate:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content=_public_paper(duplicate, duplicate=True),
                )

            extracted, pages, sections = _extract_pdf(temp_pdf, filename)
            paper_id = uuid.uuid4()
            work_id = derive_work_id(
                SourceIdentifiers.model_validate(extracted["identifiers"]),
                extracted["title"],
            )
            signature = content_signature(pages)
            matches = []
            for existing in _all_metadata():
                other = existing.get("content_signature")
                if other is None:
                    old_pages = [_read_metadata(p) or {} for p in sorted(
                        (_papers_dir() / existing["paper_id"] / "pages").glob("*.json"))]
                    other = content_signature(old_pages)
                score = overlap(signature, other)
                identifiers = existing.get("identifiers") or {}
                shared_id = bool(
                    extracted["identifiers"].get("arxiv_id") and
                    extracted["identifiers"]["arxiv_id"] == identifiers.get("arxiv_id")
                    or extracted["identifiers"].get("doi") and
                    extracted["identifiers"]["doi"].lower() == (identifiers.get("doi") or "").lower())
                if shared_id or score >= 0.55:
                    matches.append({"paper": _public_paper(existing), "score": round(score, 4),
                                    "basis": "identifier_and_content" if shared_id and score >= .55 else
                                             "identifier" if shared_id else "content_overlap"})
            matches.sort(key=lambda m: m["score"], reverse=True)
            if matches:
                work_id = matches[0]["paper"]["work_id"]
            if matches and conflict_action == "ask":
                newest = max((m["paper"] for m in matches), key=lambda m: m.get("version_number") or -1)
                return JSONResponse(status_code=409, content={
                    "conflict": True, "incoming": {"filename": filename, "title": extracted["title"],
                    "version_label": extracted["version_label"], "version_number": extracted["version_number"]},
                    "matches": matches[:10], "latest": newest,
                    "recommendation": "keep_existing_newer" if
                    newest.get("version_number") is not None and extracted["version_number"] is not None
                    and newest["version_number"] > extracted["version_number"]
                    else "review_versions",
                    "method_note": "正文五词片段重合率 + 标识核对；不是深层语义 embedding。"})
            replacement = None
            if conflict_action == "replace":
                replacement = next((m["paper"] for m in matches if m["paper"]["paper_id"] == target_paper_id), None)
                if replacement is None or replacement["sha256"] != target_sha256:
                    raise HTTPException(409, "目标记录已变化或不是关联论文，请重新检查后选择。")
                if replacement['paper_id'] in ocr._ACTIVE or jobs.busy(replacement['paper_id']):
                    raise HTTPException(409,'目标论文任务正在运行，请完成后再替换。')
            chunks = build_chunks(
                pages,
                sections,
                paper_id=str(paper_id),
                work_id=work_id,
                version_label=extracted["version_label"],
            )
            needs_ocr_pages = [page["page"] for page in pages if page["needs_ocr"]]
            warnings = []
            if needs_ocr_pages:
                warnings.append(f"{len(needs_ocr_pages)} page(s) have little or no text and may need OCR")
            if not extracted["title"]:
                warnings.append("PDF metadata does not include a title")
            if not sections and not needs_ocr_pages:
                warnings.append("No section headings were detected")

            parse_status = "needs_ocr" if needs_ocr_pages else "ready"
            metadata = PaperMetadataRecord(
                paper_id=str(paper_id),
                work_id=work_id,
                filename=filename,
                sha256=sha256,
                **extracted,
                parse_status=parse_status,
                needs_ocr_pages=needs_ocr_pages,
                section_count=len(sections),
                chunk_count=len(chunks),
                created_at=datetime.now(timezone.utc).isoformat(),
                warnings=warnings,
            ).model_dump(mode="json")

            metadata["content_signature"] = signature
            metadata["match_method"] = matches[0]["basis"] if matches else None
            page_dir = staging_dir / "pages"
            page_dir.mkdir()
            for page in pages:
                _write_json(page_dir / f"{page['page']:06d}.json", page)
            _write_json(staging_dir / "structure.json", {"sections": sections, "chunks": chunks})
            _write_json(staging_dir / "metadata.json", metadata)
            os.replace(temp_pdf, staging_dir / "source.pdf")
            staged_bytes = sum(path.stat().st_size for path in staging_dir.rglob("*") if path.is_file())
            if _storage_usage_bytes() + staged_bytes > MAX_STORAGE_BYTES:
                raise HTTPException(status_code=507, detail="Paper storage quota reached")
            destination = papers_dir / str(paper_id)
            os.replace(staging_dir, destination)
            if replacement:
                # Keep the previous source addressable for old evidence links.
                old_path = _papers_dir() / replacement["paper_id"] / "metadata.json"
                old_metadata = _read_metadata(old_path)
                old_metadata.update(archived=True, replaced_by=str(paper_id))
                try:
                    _write_json(old_path.with_suffix(".tmp"), old_metadata)
                    os.replace(old_path.with_suffix(".tmp"), old_path)
                except OSError:
                    shutil.rmtree(destination, ignore_errors=True)
                    raise
            result = _public_paper(metadata)
            result["replaced_paper_id"] = replacement["paper_id"] if replacement else None
            return result
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
    papers = [_public_paper(metadata) for metadata in _all_metadata()]
    papers.sort(key=lambda item: item["created_at"], reverse=True)
    return {"items": papers[offset : offset + limit], "total": len(papers)}


@router.get("/{paper_id}")
def get_paper(paper_id: uuid.UUID) -> dict[str, Any]:
    return _public_paper(_load_paper(paper_id))


@router.delete("/{paper_id}", status_code=204)
def delete_paper(paper_id: uuid.UUID):
    """Permanently delete exactly one record and its derived files."""
    # Share the scheduling lock so OCR cannot start between the check and removal.
    from app import ocr, jobs
    with ocr._LOCK, jobs._LOCK, _STORE_LOCK:
        _load_paper(paper_id)
        if str(paper_id) in ocr._ACTIVE:
            raise HTTPException(409, "该论文正在 OCR 识别，请等待处理结束后再删除。")
        if jobs.busy(paper_id):
            raise HTTPException(409, '该论文有后台解析或翻译任务，请等待处理结束后再删除。')
        directory = _papers_dir() / str(paper_id)
        try:
            shutil.rmtree(directory)
        except OSError as error:
            raise HTTPException(503, "删除未完成，请刷新论文库后重试。") from error
    return Response(status_code=204)


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


@router.get("/{paper_id}/structure")
def get_paper_structure(paper_id: uuid.UUID) -> dict[str, Any]:
    metadata = _load_paper(paper_id)
    structure_path = _papers_dir() / str(paper_id) / "structure.json"
    structure = _read_metadata(structure_path) or {"sections": [], "chunks": []}
    sections = structure.get("sections", [])
    chunks = structure.get("chunks", [])
    return {
        "paper_id": str(paper_id),
        "section_count": metadata.get("section_count", len(sections)),
        "chunk_count": metadata.get("chunk_count", len(chunks)),
        "sections": sections,
    }


@router.get("/{paper_id}/chunks")
def get_paper_chunks(
    paper_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _load_paper(paper_id)
    structure_path = _papers_dir() / str(paper_id) / "structure.json"
    structure = _read_metadata(structure_path) or {"chunks": []}
    chunks = structure.get("chunks", [])
    return {
        "paper_id": str(paper_id),
        "items": chunks[offset : offset + limit],
        "total": len(chunks),
    }


@router.get("/{paper_id}/source.pdf")
def source_pdf(paper_id: uuid.UUID):
    _load_paper(paper_id)
    return FileResponse(_papers_dir()/str(paper_id)/"source.pdf", media_type="application/pdf",
                        filename="source.pdf", content_disposition_type="inline")


_RENDER_SLOT = threading.BoundedSemaphore(2)


@router.get("/{paper_id}/render/{page_number}")
def render_page(paper_id: uuid.UUID, page_number: int):
    metadata = _load_paper(paper_id)
    if not 1 <= page_number <= metadata["page_count"]:
        raise HTTPException(404, "Page not found")
    if not _RENDER_SLOT.acquire(blocking=False):
        raise HTTPException(429, "页面渲染繁忙，请稍后重试。")
    try:
        with fitz.open(_papers_dir()/str(paper_id)/"source.pdf") as document:
            page = document[page_number-1]
            scale = min(1.8, 2200/max(page.rect.width, page.rect.height))
            image = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
        return Response(image, media_type="image/png")
    finally:
        _RENDER_SLOT.release()
