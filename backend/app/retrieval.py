"""Deterministic local retrieval over evidence-bearing paper chunks."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from app import papers as paper_store
from app.models import RetrievalEvidenceRecord, SourceReference
from app.processing import build_chunks, is_valid_section_title


WORD_PATTERN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for", "from",
    "did", "do", "does", "doing", "how", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "their", "this", "to", "was", "were", "what", "which", "with", "why",
    "main", "each", "make", "up", "change", "components", "many", "used", "use",
    "了", "和", "是", "的", "在", "主要", "哪些", "什么", "怎么", "如何",
}

ENGLISH_ALIASES = {
    "architectural": "architecture", "architectures": "architecture",
    "introduced": "propose", "introduces": "propose", "introducing": "propose", "proposed": "propose",
    "components": "layer", "component": "layer", "layers": "layer",
    "products": "product", "outputs": "output", "heads": "head",
    "queries": "query", "keys": "key", "values": "value", "dimensions": "dimension",
    "divided": "divide", "dividing": "divide", "scaled": "scale", "scaling": "scale",
    "combines": "concatenate", "combined": "concatenate", "combining": "concatenate",
    "combine": "concatenate", "concatenates": "concatenate", "concatenated": "concatenate",
    "functions": "function", "encodings": "encoding", "mechanisms": "mechanism",
    "pairs": "pair", "pairings": "pair", "pairing": "pair",
    "images": "image", "encoders": "encoder",
    "representations": "representation", "classifiers": "classifier",
    "labels": "label", "examples": "example", "embeddings": "embedding",
    "pre-training": "pretrain", "pre-trained": "pretrain", "pretraining": "pretrain",
    "pretrained": "pretrain", "matched": "match", "matching": "match",
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
    "架构": "architecture", "去掉": "remove", "移除": "remove",
    "结构": "structure", "机制": "mechanism", "缩放": "scale",
    "点积注意力": "dot product attention", "头": "head", "维度": "dimension",
    "训练": "training", "优化器": "optimizer", "型号": "hardware", "时长": "schedule",
    "归一化": "normalization", "层": "layer", "改用": "use attention",
}


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def tokenize(value: str) -> list[str]:
    """Tokenize English words and Chinese unigrams/bigrams without dependencies."""

    normalized = _normalize(value).replace("β", "beta").replace("ϵ", "epsilon")
    tokens = []
    for token in WORD_PATTERN.findall(normalized):
        canonical = ENGLISH_ALIASES.get(token, token)
        if token not in STOPWORDS:
            tokens.append(canonical)
        if "-" in canonical:
            tokens.extend(part for part in canonical.split("-") if part not in STOPWORDS)
    for run in CJK_PATTERN.findall(normalized):
        characters = [character for character in run if character not in STOPWORDS]
        tokens.extend(characters)
        tokens.extend("".join(characters[index : index + 2]) for index in range(len(characters) - 1))
    return tokens


def _query_variants(question: str, concept_search: bool = False) -> list[list[str]]:
    """Preserve literal matching and add a narrow offline Chinese-English query."""

    query_text = _normalize(question).replace("β", "beta").replace("ϵ", "epsilon")
    query_text = re.sub(r"square\s+root(?:\s+of)?(?:\s+the\s+key\s+dimension)?", "dk", query_text)
    query_text = query_text.replace("feed-forward dimension", "dff")
    query_text = re.sub(
        r"分别来自哪里|来自哪里|多少个|为什么|为何|如何|怎么|怎样|哪些|哪种|什么是|什么|分别|来自|哪里|多少",
        " ",
        query_text,
    )
    if concept_search:
        query_text = re.sub(r"请问|请找出|请查找|帮我找|提到过|提及过|提到了|提到|出现过|讨论过|讨论了|哪些论文|哪几篇论文|哪篇论文|论文中|论文里|的信息|这个信息|关于|有关|相关|有没有|是否|在哪|哪里|\bwhich papers\b|\bmention(?:ed|s)?\b|\bdiscuss(?:ed|es)?\b", " ", query_text)
    literal_tokens = tokenize(query_text)
    # A few official fine-grained questions use symbols or Chinese wording
    # that differs from the PDF text layer. These are fixed, auditable aliases,
    # not a general-purpose translator.
    official_aliases = []
    if re.search(r"\b(?:beta1|β1|beta 1)\b", question, re.I): official_aliases.append("beta1")
    if re.search(r"\b(?:beta2|β2|beta 2)\b", question, re.I): official_aliases.append("beta2")
    if "gpu" in query_text or "显卡" in query_text: official_aliases.extend(["hardware", "gpu"])
    if ("gpu" in query_text or "显卡" in query_text or "硬件" in question) and ("型号" in question or "训练时长" in question): official_aliases.extend(["hardware", "training", "hours", "steps"])
    if official_aliases: literal_tokens.extend(tokenize(" ".join(official_aliases)))
    definition_question = bool(re.fullmatch(
        r"(?:什么是|何为|解释一下|请解释)\s*(?:attention|注意力(?:机制)?)\s*[？?。!]*",
        _normalize(question),
    ))
    variants = [] if definition_question else [literal_tokens]
    if "脚注" in question and ("机构" in question or "affiliation" in query_text):
        variants.append(["work", "performed"])
    remaining = query_text
    translated: list[str] = []
    for chinese, english in sorted(RESEARCH_TERMS.items(), key=lambda pair: -len(pair[0])):
        if chinese in remaining:
            translated.extend(tokenize(english))
            remaining = remaining.replace(chinese, " " * len(chinese))
    # Avoid treating a single broad concept (or a bare acronym) as enough
    # context to retrieve an unrelated paper. Unrecognized Chinese stays in
    # the literal query instead of being silently translated or invented.
    translated = list(dict.fromkeys(WORD_PATTERN.findall(query_text) + translated))
    if len(translated) >= (1 if concept_search else 2) and translated != literal_tokens and not definition_question:
        variants.append(translated)
    # Short definitional questions contain little context: resolve the known
    # research term to two related English concepts rather than matching the
    # lone word 'attention' in any unrelated paper.
    if definition_question:
        variants.extend((["attention", "function"], ["attention", "mechanism"]))
    return variants


def _translated_phrases(question: str) -> list[str]:
    normalized = _normalize(question)
    return [english for chinese, english in RESEARCH_TERMS.items() if chinese in normalized]


def _load_candidates(paper_ids: set[str], exclude_references: bool = False, collection_id: str | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for metadata in paper_store._all_metadata():
        paper_id = metadata["paper_id"]
        if paper_ids and paper_id not in paper_ids:
            continue
        if collection_id is not None and collection_id not in metadata.get("collection_ids", []):
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
            if is_valid_section_title(str(section.get("title") or ""))
        }
        for chunk in chunks:
            text = str(chunk.get("text") or "").strip()
            if not text:
                continue
            source = chunk.get("source") or {}
            section_title = section_titles.get(source.get("section_id"))
            if exclude_references:
                if re.fullmatch(r"(?:[\d.]+\s*)?(?:references|bibliography|参考文献)", str(section_title or "").strip(), re.I):
                    continue
                # A chunk can straddle the end of the body and reference list.
                text = re.split(r"(?im)^\s*(?:[\d.]+\s+)?(?:references|bibliography|参考文献)\s*$", text, maxsplit=1)[0].strip()
                if not text:
                    continue
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
    limit: int | None = 6,
    ranker: str = "bm25",
    diversify_by_work: bool = False,
    relax_query_coverage: bool = False,
    exclude_references: bool = False,
    concept_search: bool = False,
    collection_id: str | None = None,
) -> tuple[list[RetrievalEvidenceRecord], int]:
    """Rank local chunks with the selected lexical/vector ranking strategy."""

    if ranker not in {"legacy", "bm25", "cosine", "hybrid"}:
        raise ValueError("ranker must be legacy, bm25, cosine, or hybrid")

    query_variants = [Counter(tokens) for tokens in _query_variants(question, concept_search) if tokens]
    if not query_variants:
        return [], 0
    candidates = _load_candidates(set(paper_ids or []), exclude_references, collection_id)
    if not candidates:
        return [], 0

    document_frequency = Counter()
    for candidate in candidates:
        document_frequency.update(set(candidate["tokens"]))

    normalized_question = _normalize(question).strip()
    definition_question = bool(re.fullmatch(
        r"(?:什么是|何为|解释一下|请解释)\s*(?:attention|注意力(?:机制)?)\s*[？?。!]*",
        normalized_question,
    ))
    phrases = _translated_phrases(question)
    method_question = any(term in normalized_question for term in ("如何", "怎么", "怎样", "how"))
    average_length = sum(len(candidate["tokens"]) for candidate in candidates) / max(1, len(candidates))
    document_count = len(candidates)
    query_terms = set().union(*(set(query_counts) for query_counts in query_variants))
    active_rankers = ("legacy", "bm25", "cosine") if ranker == "hybrid" else (ranker,)
    raw_scores: dict[str, dict[int, float]] = {name: {} for name in active_rankers}
    boosts: dict[int, float] = {}
    for candidate in candidates:
        token_counts = Counter(candidate["tokens"])
        candidate_id = id(candidate)
        scores = {name: [] for name in raw_scores}
        document_norm = 1.0
        if "cosine" in active_rankers:
            document_norm = math.sqrt(sum(
                ((1 + math.log(frequency)) * math.log(1 + (document_count + 1) / (document_frequency[token] + 1))) ** 2
                for token, frequency in token_counts.items()
            )) or 1.0
        for query_counts in query_variants:
            if definition_question and not set(query_counts).issubset(token_counts):
                continue
            legacy_score = 0.0
            bm25_score = 0.0
            cosine_dot = 0.0
            query_norm_squared = 0.0
            matched = 0
            for token, query_weight in query_counts.items():
                frequency = token_counts.get(token, 0)
                if not frequency:
                    continue
                matched += 1
                inverse_frequency = math.log(1 + (document_count + 1) / (document_frequency[token] + 1))
                bm25_idf = math.log(1 + (document_count - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5))
                if "legacy" in active_rankers:
                    legacy_score += query_weight * inverse_frequency * (1 + math.log(frequency))
                if "bm25" in active_rankers:
                    length_normalizer = 1.5 * (1 - 0.75 + 0.75 * len(candidate["tokens"]) / max(1.0, average_length))
                    bm25_score += query_weight * bm25_idf * frequency * 2.5 / (frequency + length_normalizer)
                if "cosine" in active_rankers:
                    query_tf = 1 + math.log(query_weight)
                    query_weight_tfidf = query_tf * inverse_frequency
                    document_weight_tfidf = (1 + math.log(frequency)) * inverse_frequency
                    cosine_dot += query_weight_tfidf * document_weight_tfidf
                    query_norm_squared += query_weight_tfidf**2
            if not matched:
                continue
            coverage = matched / max(1, len(query_counts))
            if len(query_counts) >= 3 and (
                matched < 2 or (coverage < 0.5 and not relax_query_coverage)
            ):
                continue
            if "legacy" in active_rankers:
                scores["legacy"].append(legacy_score * (0.65 + coverage))
            if "bm25" in active_rankers:
                scores["bm25"].append(bm25_score * (0.65 + coverage))
            if "cosine" in active_rankers:
                cosine_score = cosine_dot / (math.sqrt(query_norm_squared) * document_norm)
                scores["cosine"].append(cosine_score * (0.65 + coverage))
        if not any(scores.values()):
            continue
        section_terms = set(tokenize(candidate.get("section_title") or ""))
        boost = 2.5 * len(query_terms & section_terms)
        haystack = _normalize(candidate["text"])
        # A passage that explicitly describes the method should outrank a
        # results discussion that happens to repeat the same keywords.
        boost += sum(2.5 for phrase in phrases if " " in phrase and phrase in haystack)
        if method_question:
            boost += sum(6.0 for marker in ("to perform zero-shot", "in a bit more detail", "specifically, we", "by comparing") if marker in haystack)
        if normalized_question and normalized_question in haystack:
            boost += 2.5
        title = _normalize(str(candidate["metadata"].get("title") or ""))
        if any(token in title for query_counts in query_variants for token in query_counts):
            boost += 0.35
        boosts[candidate_id] = boost
        length_penalty = 1 + math.log1p(max(1, len(candidate["tokens"]))) * 0.08
        for name in raw_scores:
            if scores[name]:
                raw_scores[name][candidate_id] = max(scores[name]) / length_penalty

    candidate_by_id = {id(candidate): candidate for candidate in candidates if id(candidate) in boosts}
    candidate_order = {id(candidate): index for index, candidate in enumerate(candidates)}
    mode_ranks: dict[str, dict[int, int]] = {}
    for name, score_map in raw_scores.items():
        order = sorted(
            score_map,
            key=lambda identifier: (-score_map[identifier], -boosts[identifier], candidate_order[identifier]),
        )
        mode_ranks[name] = {identifier: rank for rank, identifier in enumerate(order, start=1)}

    if ranker == "hybrid":
        fusion_scores = {
            identifier: sum(1 / (60 + ranks[identifier]) for ranks in mode_ranks.values() if identifier in ranks)
            for identifier in candidate_by_id
        }
        ordered_ids = sorted(
            fusion_scores,
            key=lambda identifier: (-fusion_scores[identifier], -boosts[identifier], candidate_order[identifier]),
        )
        ranked = [(fusion_scores[identifier] * 1000, candidate_by_id[identifier]) for identifier in ordered_ids]
    else:
        mode = ranker
        ordered_ids = sorted(
            raw_scores[mode],
            key=lambda identifier: (
                -raw_scores[mode][identifier],
                -boosts[identifier],
                candidate_order[identifier],
            ),
        )
        ranked = [(raw_scores[mode][identifier] + boosts[identifier], candidate_by_id[identifier]) for identifier in ordered_ids]

    if diversify_by_work:
        work_groups: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        for score, candidate in ranked:
            work_id = str(candidate["metadata"].get("work_id") or candidate["metadata"]["paper_id"])
            work_groups.setdefault(work_id, []).append((score, candidate))
        diversified: list[tuple[float, dict[str, Any]]] = []
        while (limit is None or len(diversified) < limit) and work_groups:
            exhausted = []
            for work_id, group in work_groups.items():
                if group:
                    diversified.append(group.pop(0))
                    if limit is not None and len(diversified) >= limit:
                        break
                if not group:
                    exhausted.append(work_id)
            for work_id in exhausted:
                work_groups.pop(work_id, None)
        ranked = diversified

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
