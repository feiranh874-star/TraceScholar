"""Deterministic metadata, structure, and chunk extraction for local PDFs."""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

import pymupdf as fitz

from app.models import (
    PageRecord,
    SectionRecord,
    SourceIdentifiers,
    SourceReference,
    TextChunkRecord,
)


ARXIV_PATTERN = re.compile(r"(?<!\d)(?P<identifier>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?", re.IGNORECASE)
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
SECTION_NUMBER_PATTERN = re.compile(r"^(?P<number>[1-9]\d*(?:\.\d+)*)\.?$")
SECTION_INLINE_PATTERN = re.compile(r"^(?P<number>[1-9]\d*(?:\.\d+)*)\.?\s+(?P<title>[A-Z][^\n]{1,100})$")
COMMON_UNNUMBERED_SECTIONS = {"abstract", "references", "appendix", "acknowledgements", "acknowledgments"}
AFFILIATION_WORDS = {
    "academy",
    "brain",
    "center",
    "centre",
    "company",
    "department",
    "google",
    "institute",
    "laboratory",
    "labs",
    "meta",
    "microsoft",
    "openai",
    "research",
    "school",
    "university",
}
TITLE_EXCLUSIONS = (
    "provided proper attribution",
    "permission to reproduce",
    "conference on",
    "arxiv:",
)


def detect_identifiers(filename: str, text: str) -> tuple[SourceIdentifiers, str | None, int | None]:
    arxiv_match = ARXIV_PATTERN.search(filename) or ARXIV_PATTERN.search(text[:20_000])
    arxiv_id = arxiv_match.group("identifier") if arxiv_match else None
    version_number = int(arxiv_match.group("version")) if arxiv_match and arxiv_match.group("version") else None
    version_label = f"v{version_number}" if version_number is not None else None

    doi_match = DOI_PATTERN.search(text[:100_000])
    doi = doi_match.group(0).rstrip(".,;:)]}") if doi_match else None
    return SourceIdentifiers(arxiv_id=arxiv_id, doi=doi), version_label, version_number


def derive_work_id(identifiers: SourceIdentifiers, title: str | None) -> str:
    if identifiers.arxiv_id:
        key = f"https://arxiv.org/abs/{identifiers.arxiv_id}"
    elif identifiers.doi:
        key = f"https://doi.org/{identifiers.doi.lower()}"
    elif title:
        normalized = unicodedata.normalize("NFKC", title).casefold()
        normalized = re.sub(r"\W+", " ", normalized).strip()
        key = f"tracescholar:title:{normalized}"
    else:
        return str(uuid.uuid4())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _page_lines_with_sizes(page: fitz.Page) -> list[tuple[str, float, float]]:
    values: list[tuple[str, float, float]] = []
    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if text:
                size = max((float(span.get("size", 0)) for span in spans), default=0)
                y_position = min((float(span.get("bbox", (0, 0, 0, 0))[1]) for span in spans), default=0)
                values.append((text, size, y_position))
    return values


def extract_title(page: fitz.Page, embedded_title: str | None) -> str | None:
    if embedded_title and embedded_title.strip():
        return embedded_title.strip()

    candidates = []
    for text, size, y_position in _page_lines_with_sizes(page):
        lowered = text.casefold()
        if not 5 <= len(text) <= 240:
            continue
        if "@" in text or lowered in COMMON_UNNUMBERED_SECTIONS:
            continue
        if any(excluded in lowered for excluded in TITLE_EXCLUSIONS):
            continue
        if ARXIV_PATTERN.search(text) or not any(character.isalpha() for character in text):
            continue
        candidates.append((size, -y_position, text))
    if not candidates:
        return None
    return max(candidates)[2]


def _clean_person_name(value: str) -> str:
    value = re.sub(r"[\s*\u2217\u2020\u2021]+$", "", value).strip()
    return re.sub(r"\s+", " ", value)


def _looks_like_person_name(value: str, title: str | None) -> bool:
    lowered = value.casefold()
    if not value or value == title or any(word in lowered.split() for word in AFFILIATION_WORDS):
        return False
    if any(character.isdigit() for character in value) or len(value) > 80:
        return False
    words = value.replace("-", " ").split()
    return 2 <= len(words) <= 6 and all(any(character.isalpha() for character in word) for word in words)


def extract_authors(first_page_text: str, title: str | None, embedded_author: str | None) -> list[str]:
    if embedded_author and embedded_author.strip():
        return [item.strip() for item in re.split(r"[,;]", embedded_author) if item.strip()]

    before_abstract = re.split(r"\n\s*Abstract\s*\n", first_page_text, maxsplit=1, flags=re.IGNORECASE)[0]
    lines = [line.strip() for line in before_abstract.splitlines() if line.strip()]
    authors: list[str] = []
    for index, line in enumerate(lines):
        if "@" not in line:
            continue
        for candidate_index in range(index - 1, max(-1, index - 5), -1):
            candidate = _clean_person_name(lines[candidate_index])
            if _looks_like_person_name(candidate, title):
                if candidate not in authors:
                    authors.append(candidate)
                break
    return authors


def extract_abstract(first_page_text: str) -> str | None:
    match = re.search(r"\n\s*Abstract\s*\n(?P<body>.+)", first_page_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    body = match.group("body")
    endings = [
        re.search(r"\n\s*1\s*\n\s*Introduction\s*\n|\n\s*1\s+Introduction\s*\n", body, flags=re.IGNORECASE),
        re.search(r"\n\s*[\u2217*\u2020\u2021]\s*Equal contribution", body, flags=re.IGNORECASE),
        re.search(r"\n\s*\d+(?:st|nd|rd|th)\s+Conference", body, flags=re.IGNORECASE),
        re.search(r"\n\s*arXiv:", body, flags=re.IGNORECASE),
    ]
    ending_positions = [ending.start() for ending in endings if ending]
    if ending_positions:
        body = body[: min(ending_positions)]
    body = re.sub(r"\s+", " ", body).strip()
    return body or None


def is_valid_section_title(value: str) -> bool:
    value = value.strip()
    if not 2 <= len(value) <= 100 or value.endswith((".", ",", ";", ":", "-", "–", "—")):
        return False
    if len(value.split()) > 14 or "@" in value:
        return False
    if not value[0].isalpha() or sum(character.isalpha() for character in value) < 2:
        return False
    if value[0].isascii() and not value[0].isupper():
        return False
    words = re.findall(r"[A-Za-z]+", value)
    if len(words) >= 6 and sum(word[0].isupper() for word in words) / len(words) < 0.45:
        return False
    if "%" in value or "\u00b7" in value or "\u2022" in value:
        return False
    return True


def _valid_section_number(value: str) -> bool:
    parts = [int(part) for part in value.split(".")]
    return 1 <= parts[0] <= 20 and all(0 <= part <= 20 for part in parts[1:])


def _looks_like_running_header(value: str) -> bool:
    words = re.findall(r"[A-Za-z]+", value)
    if len(words) < 5:
        return False
    return sum(word[0].isupper() for word in words) / len(words) >= 0.7


def extract_sections(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()
    for page in pages:
        lines: list[tuple[str, int]] = []
        cursor = 0
        for raw_line in page["text"].splitlines():
            line = raw_line.strip()
            if not line:
                cursor += len(raw_line) + 1
                continue
            position = page["text"].find(line, cursor)
            position = cursor if position < 0 else position
            lines.append((line, position))
            cursor = position + len(line) + 1

        if any(line.casefold() in {"contents", "table of contents"} for line, _ in lines[:8]):
            continue

        for index, (line, line_position) in enumerate(lines):
            number: str | None = None
            title: str | None = None
            number_match = SECTION_NUMBER_PATTERN.fullmatch(line)
            inline_match = SECTION_INLINE_PATTERN.fullmatch(line)
            if (
                number_match
                and number_match.group("number") == str(page["page"])
                and (
                    (
                        index == 0
                        and not (
                            index + 1 < len(lines)
                            and is_valid_section_title(lines[index + 1][0])
                        )
                    )
                    or index == len(lines) - 1
                    or (
                        0 < index <= 2
                        and _looks_like_running_header(lines[index - 1][0])
                    )
                )
            ):
                # Running page numbers often sit directly before body text and
                # otherwise look like a numbered heading in extracted PDF text.
                continue
            if (
                number_match
                and _valid_section_number(number_match.group("number"))
                and index + 1 < len(lines)
                and is_valid_section_title(lines[index + 1][0])
            ):
                number = number_match.group("number")
                title = lines[index + 1][0]
            elif (
                inline_match
                and _valid_section_number(inline_match.group("number"))
                and is_valid_section_title(inline_match.group("title"))
            ):
                number = inline_match.group("number")
                title = inline_match.group("title")
            elif line.casefold() in COMMON_UNNUMBERED_SECTIONS:
                title = line.title()

            if title is None:
                continue
            key = (number, title.casefold())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "number": number,
                    "title": title,
                    "level": number.count(".") + 1 if number else 1,
                    "page_start": page["page"],
                    "page_char_start": line_position,
                }
            )

    sections: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        next_page = candidates[index + 1]["page_start"] if index + 1 < len(candidates) else pages[-1]["page"]
        page_end = max(candidate["page_start"], next_page - 1)
        sections.append(
            SectionRecord(
                section_id=f"section-{index + 1:04d}",
                page_end=page_end,
                **candidate,
            ).model_dump(mode="json")
        )
    return sections


def _section_for_position(page_number: int, char_start: int, sections: list[dict[str, Any]]) -> str | None:
    eligible = [
        section
        for section in sections
        if section["page_start"] < page_number
        or (section["page_start"] == page_number and section["page_char_start"] <= char_start)
    ]
    return eligible[-1]["section_id"] if eligible else None


def _split_page_text(text: str, target_chars: int = 1200, overlap_chars: int = 160) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target_chars)
        if end < len(text):
            break_at = max(text.rfind("\n\n", start + 400, end), text.rfind("\n", start + 400, end))
            if break_at > start:
                end = break_at
        content = text[start:end].strip()
        if content:
            leading = len(text[start:end]) - len(text[start:end].lstrip())
            actual_start = start + leading
            chunks.append((actual_start, actual_start + len(content), content))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def build_chunks(
    pages: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    *,
    paper_id: str,
    work_id: str,
    version_label: str | None,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page in pages:
        if not page["text"].strip():
            continue
        page_sections = sorted(
            (section for section in sections if section["page_start"] == page["page"]),
            key=lambda section: section["page_char_start"],
        )
        segment_starts = sorted({0, *(section["page_char_start"] for section in page_sections)})
        for segment_index, segment_start in enumerate(segment_starts):
            segment_end = segment_starts[segment_index + 1] if segment_index + 1 < len(segment_starts) else len(page["text"])
            segment_text = page["text"][segment_start:segment_end]
            section_id = _section_for_position(page["page"], segment_start, sections)
            for relative_start, relative_end, text in _split_page_text(segment_text):
                char_start = segment_start + relative_start
                char_end = segment_start + relative_end
                chunk_id = f"chunk-{len(chunks) + 1:06d}"
                source = SourceReference(
                    paper_id=paper_id,
                    work_id=work_id,
                    version_label=version_label,
                    page_start=page["page"],
                    page_end=page["page"],
                    section_id=section_id,
                    bbox=None,
                )
                chunks.append(
                    TextChunkRecord(
                        chunk_id=chunk_id,
                        text=text,
                        char_count=len(text),
                        char_start=char_start,
                        char_end=char_end,
                        source=source,
                    ).model_dump(mode="json")
                )
    return chunks


def extract_document_metadata(
    document: fitz.Document,
    pages: list[dict[str, Any]],
    filename: str,
) -> dict[str, Any]:
    embedded = document.metadata or {}
    first_page_text = pages[0]["text"] if pages else ""
    sample_text = "\n".join(page["text"] for page in pages[:3])
    identifiers, version_label, version_number = detect_identifiers(filename, sample_text)
    title = extract_title(document.load_page(0), (embedded.get("title") or "").strip() or None)
    authors = extract_authors(first_page_text, title, (embedded.get("author") or "").strip() or None)
    return {
        "title": title,
        "author": ", ".join(authors) or None,
        "authors": authors,
        "abstract": extract_abstract(first_page_text),
        "identifiers": identifiers.model_dump(mode="json"),
        "version_label": version_label,
        "version_number": version_number,
    }

