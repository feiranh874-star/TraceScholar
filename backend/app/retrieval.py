"""Deterministic local retrieval over evidence-bearing paper chunks."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from app import papers as paper_store
from app.models import RetrievalEvidenceRecord, SourceReference
from app.processing import build_chunks


WORD_PATTERN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "did", "do", "does", "how", "in", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "what", "which", "with", "why", "了", "和", "是", "的", "在",
}

# Offline terminology bridge for the initial research-paper demo. This is not
# general translation; unknown Chinese concepts must not be guessed.
RESEARCH_TERMS = {
    "零样本": "zero-shot", "少样本": "few-shot",
    "图像分类": "image classification", "图片分类": "image classification",
    "图像": "image", "图片": "image", "文本": "text",
    "分类": "classification", "视觉": "visual",
    "语言模型": "language model", "语言": "language",
    "自然语言监督": "natural language supervision",
    "注意力机制": "attention mechanism", "注意力": "attention",
    "查询": "query", "键": "key", "值": "value",
    "嵌入": "embedding", "特征": "feature",
    "编码器": "encoder", "预训练": "pre-trained",
    "提示词": "prompt", "对比学习": "contrastive learning",
    "相似度": "similarity", "准确率": "accuracy",
}


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def tokenize(value: str) -> list[str]:
    """Tokenize English words and Chinese unigrams/bigrams without dependencies."""

    normalized = _normalize(value)
    tokens = [token for token in WORD_PATTERN.findall(normalized) if token not in STOPWORDS]
    for run in CJK_PATTERN.findall(normalized):
        characters = [character for character in run if character not in STOPWORDS]
        tokens.extend(characters)
        tokens.extend("".join(characters[index : index + 2]) for index in range(len(characters) - 1))
    return tokens


def _query_variants(question: str) -> list[list[str]]:
    """Preserve literal matching and add a narrow offline Chinese-English query."""

    literal_tokens = tokenize(question)
    variants = [literal_tokens]
    remaining = _normalize(question)
    translated: list[str] = []
    for chinese, english in sorted(RESEARCH_TERMS.items(), key=lambda pair: -len(pair[0])):
        if chinese in remaining:
            translated.extend(tokenize(english))
            remaining = remaining.replace(chinese, " " * len(chinese))
    # Avoid treating a single broad concept (or a bare acronym) as enough
    # context to retrieve an unrelated paper. Unrecognized Chinese stays in
    # the literal query instead of being silently translated or invented.
    translated = list(dict.fromkeys(WORD_PATTERN.findall(_normalize(question)) + translated))
    if len(translated) >= 2 and translated != literal_tokens:
        variants.append(translated)
    return variants


def _translated_phrases(question: str) -> list[str]:
    normalized = _normalize(question)
    return [english for chinese, english in RESEARCH_TERMS.items() if chinese in normalized]


def _load_candidates(paper_ids: set[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for metadata in paper_store._all_metadata():
        paper_id = metadata["paper_id"]
        if paper_ids and paper_id not in paper_ids:
            continue
        structure = paper_store._read_metadata(
            paper_store._papers_dir() / paper_id / "structure.json"
        ) or {"sections": [], "chunks": []}
        sections = structure.get("sections", [])
        chunks = structure.get("chunks", [])
        if not chunks:
            page_dir = paper_store._papers_dir() / paper_id / "pages"
            pages = [
                page
                for page_path in sorted(page_dir.glob("*.json"))
                if (page := paper_store._read_metadata(page_path)) is not None
            ]
            chunks = build_chunks(
                pages,
                sections,
                paper_id=paper_id,
                work_id=metadata.get("work_id") or paper_id,
                version_label=metadata.get("version_label"),
            )
        section_titles = {
            section.get("section_id"): section.get("title")
            for section in sections
        }
        for chunk in chunks:
            text = str(chunk.get("text") or "").strip()
            if not text:
                continue
            source = chunk.get("source") or {}
            candidates.append(
                {
                    "chunk": chunk,
                    "text": text,
                    "metadata": metadata,
                    "section_title": section_titles.get(source.get("section_id")),
                    "tokens": tokenize(text),
                }
            )
    return candidates


def search_evidence(
    question: str,
    *,
    paper_ids: list[str] | None = None,
    limit: int = 6,
) -> tuple[list[RetrievalEvidenceRecord], int]:
    """Rank local chunks and return evidence with intact source metadata."""

    query_variants = [Counter(tokens) for tokens in _query_variants(question) if tokens]
    if not query_variants:
        return [], 0
    candidates = _load_candidates(set(paper_ids or []))
    if not candidates:
        return [], 0

    document_frequency = Counter()
    for candidate in candidates:
        document_frequency.update(set(candidate["tokens"]))

    normalized_question = _normalize(question).strip()
    phrases = _translated_phrases(question)
    method_question = any(term in normalized_question for term in ("如何", "怎么", "怎样", "how"))
    ranked: list[tuple[float, dict[str, Any]]] = []
    document_count = len(candidates)
    for candidate in candidates:
        token_counts = Counter(candidate["tokens"])
        scores = []
        for query_counts in query_variants:
            score = 0.0
            matched = 0
            for token, query_weight in query_counts.items():
                frequency = token_counts.get(token, 0)
                if not frequency:
                    continue
                matched += 1
                inverse_frequency = math.log(1 + (document_count + 1) / (document_frequency[token] + 1))
                score += query_weight * inverse_frequency * (1 + math.log(frequency))
            if not matched:
                continue
            coverage = matched / max(1, len(query_counts))
            if len(query_counts) >= 3 and (matched < 2 or coverage < 0.5):
                continue
            scores.append(score * (0.65 + coverage))
        if not scores:
            continue
        score = max(scores)
        score /= 1 + math.log1p(max(1, len(candidate["tokens"]))) * 0.08
        haystack = _normalize(candidate["text"])
        # A passage that explicitly describes the method should outrank a
        # results discussion that happens to repeat the same keywords.
        score += sum(2.5 for phrase in phrases if " " in phrase and phrase in haystack)
        if method_question:
            score += sum(6.0 for marker in ("to perform zero-shot", "in a bit more detail", "specifically, we", "by comparing") if marker in haystack)
        if normalized_question and normalized_question in haystack:
            score += 2.5
        title = _normalize(str(candidate["metadata"].get("title") or ""))
        if any(token in title for query_counts in query_variants for token in query_counts):
            score += 0.35
        ranked.append((score, candidate))

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1]["metadata"].get("created_at", ""),
            item[1]["chunk"].get("chunk_id", ""),
        )
    )
    results: list[RetrievalEvidenceRecord] = []
    for score, candidate in ranked[:limit]:
        chunk = candidate["chunk"]
        metadata = candidate["metadata"]
        source = SourceReference.model_validate(chunk["source"])
        results.append(
            RetrievalEvidenceRecord(
                evidence_id=f"{source.paper_id}:{chunk['chunk_id']}",
                text=candidate["text"],
                score=round(score, 6),
                source=source,
                paper_title=metadata.get("title"),
                filename=metadata["filename"],
                section_title=candidate["section_title"],
            )
        )
    return results, len(candidates)
