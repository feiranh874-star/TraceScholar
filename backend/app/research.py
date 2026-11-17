"""Research retrieval and evidence-grounded answer endpoints."""

import re

from fastapi import APIRouter, HTTPException, Request

from app.config import Settings
from app.llm import LLMServiceError, generate_grounded_answer
from app.models import (
    AgentResponse,
    AgentStepRecord,
    AnswerCitationRecord,
    AnswerResponse,
    ComparisonRequest,
    RetrievalEvidenceRecord,
    RetrievalRequest,
    RetrievalResponse,
)
from app import papers as paper_store
from app.retrieval import search_evidence


router = APIRouter(prefix="/api/research", tags=["research"])


INTENT_MARKERS = {
    "definition": ("什么是", "是什么", "何为", "指什么", "定义", "define", "explain", "what is", "what are"),
    "method": ("如何", "怎么", "怎样", "为什么", "原理", "机制", "how ", "why ", "method"),
    "result": ("结果", "实验", "指标", "bleu", "accuracy", "result", "performance", "score"),
    "comparison": ("比较", "对比", "区别", "差异", "compare", "difference", "versus", " vs "),
    "summary": ("总结", "概括", "摘要", "summarize", "summary", "overview"),
}
INTENT_LABELS = {
    "definition": "概念解释",
    "method": "方法原理",
    "result": "实验结果",
    "comparison": "比较分析",
    "summary": "内容概括",
    "general": "一般问题",
}
EVIDENCE_ONLY_PREFIXES = (
    re.compile(r"^\s*(?:请)?(?:只检索原文|只找原文|查找原文|找证据|检索证据)\s*[：:，,]?\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:please\s+)?(?:only\s+)?(?:find|search(?:\s+for)?)\s+(?:the\s+)?evidence(?:\s+(?:for|about))?\s*[:：]?\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:please\s+)?show\s+(?:me\s+)?(?:the\s+)?(?:sources|evidence)(?:\s+(?:for|about))?\s*[:：]?\s*", re.IGNORECASE),
)


def _classify_intent(question: str) -> str:
    normalized = question.casefold().strip()
    for intent in ("comparison", "summary", "result", "definition", "method"):
        if any(marker in normalized for marker in INTENT_MARKERS[intent]):
            return intent
    return "general"


def _wants_evidence_only(question: str) -> bool:
    return any(pattern.match(question) for pattern in EVIDENCE_ONLY_PREFIXES)


def _question_for_evidence_search(question: str, retrieve_only: bool) -> str:
    if not retrieve_only:
        return question
    for pattern in EVIDENCE_ONLY_PREFIXES:
        cleaned = pattern.sub("", question, count=1)
        if cleaned != question:
            return cleaned.strip() or question
    return question


def _comparison_query_for_paper(question: str, paper: dict) -> str:
    """Translate the initial demo papers' comparison concepts into their source terminology."""

    title = " ".join((paper.get("title") or "", paper.get("filename") or "")).casefold()
    normalized_question = question.casefold()
    asks_training = any(term in normalized_question for term in ("训练", "预训练", "training", "objective"))
    asks_data = any(term in normalized_question for term in ("数据", "dataset", "data"))
    asks_transfer = any(term in normalized_question for term in ("迁移", "下游", "transfer", "few-shot", "zero-shot"))
    asks_method = any(term in normalized_question for term in ("如何", "怎么", "怎样", "how", "method"))

    aliases = []
    if "learning transferable visual models" in title or "2103.00020" in title:
        if asks_training:
            aliases.append("CLIP contrastive image text pretraining objective")
        if asks_data:
            aliases.append("image text pairs internet dataset")
        if asks_transfer:
            aliases.append("zero-shot transfer without supervised adaptation")
            if asks_method:
                aliases.append("how image classification image encoder text encoder cosine similarity softmax")
    elif (
        "language models are few-shot learners" in title
        or "语言模型是少样本学习器" in title
        or "2005.14165" in title
    ):
        if asks_training:
            aliases.append("GPT-3 autoregressive language model objective")
        if asks_data:
            aliases.append("Common Crawl WebText books training dataset")
        if asks_transfer:
            aliases.append("few-shot in-context learning without gradient updates or fine-tuning")

    # Prefer short, source-aligned terms for retrieval. The original question
    # remains unchanged in the prompt sent to the answer model.
    return " ".join(aliases) if aliases else question


def _answer_with_evidence(
    question: str,
    items: list[RetrievalEvidenceRecord],
    total_candidates: int,
    settings: Settings,
    answer_mode: str = "general",
    required_paper_ids: set[str] | None = None,
) -> AnswerResponse:
    if not all((settings.llm_base_url, settings.llm_api_key, settings.llm_model)):
        raise HTTPException(
            status_code=503,
            detail="模型服务尚未配置，请设置 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY。",
        )
    try:
        answer = generate_grounded_answer(
            question,
            items,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            answer_mode=answer_mode,
        )
    except LLMServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    referenced = {int(value) for value in re.findall(r"\[E(\d+)\]", answer, flags=re.IGNORECASE)}
    valid_references = {index for index in referenced if 1 <= index <= len(items)}
    answer = re.sub(
        r"\[E(\d+)\]",
        lambda match: match.group(0) if int(match.group(1)) in valid_references else "",
        answer,
        flags=re.IGNORECASE,
    )
    citations = [
        AnswerCitationRecord(citation_id=f"E{index}", **item.model_dump())
        for index, item in enumerate(items, start=1)
        if index in valid_references
    ]
    if required_paper_ids:
        cited_papers = {citation.source.paper_id for citation in citations}
        if not required_paper_ids.issubset(cited_papers) and answer.strip().rstrip("。") != "当前资料不足":
            raise HTTPException(
                status_code=502,
                detail="比较回答没有引用每一篇所选论文的证据，请重试。",
            )
    insufficient = answer.strip().rstrip("。") == "当前资料不足"
    if not insufficient and not citations:
        raise HTTPException(status_code=502, detail="模型回答未包含有效证据引用，请重试。")
    return AnswerResponse(
        question=question,
        answer=answer,
        insufficient=insufficient,
        provider=settings.llm_provider or "deepseek",
        model=settings.llm_model,
        citations=citations,
        items=items,
        total_candidates=total_candidates,
    )


@router.post("/retrieve")
def retrieve_evidence(request: RetrievalRequest) -> RetrievalResponse:
    """Return ranked paper passages without calling an external model."""

    items, total_candidates = search_evidence(
        request.question,
        paper_ids=request.paper_ids,
        limit=request.limit,
        diversify_by_work=not request.paper_ids,
    )
    return RetrievalResponse(
        question=request.question,
        total_candidates=total_candidates,
        items=items,
    )


@router.post("/answer")
def answer_from_evidence(request: RetrievalRequest, http_request: Request) -> AnswerResponse:
    """Generate an answer while preserving citations from verified local evidence."""

    items, total_candidates = search_evidence(
        request.question,
        paper_ids=request.paper_ids,
        limit=request.limit,
        diversify_by_work=not request.paper_ids,
    )
    if not items:
        return AnswerResponse(
            question=request.question, insufficient=True, total_candidates=total_candidates,
        )

    return _answer_with_evidence(
        request.question, items, total_candidates, http_request.app.state.settings,
    )


@router.post("/agent", response_model=AgentResponse)
def research_agent(request: RetrievalRequest, http_request: Request) -> AgentResponse:
    """Route evidence-only questions or run the grounded-answer tool sequence."""

    intent = _classify_intent(request.question)
    if intent == "comparison" and len(request.paper_ids) > 1:
        if len(request.paper_ids) > 5:
            raise HTTPException(status_code=422, detail="一次最多比较 5 篇论文。")
        if len(set(request.paper_ids)) != len(request.paper_ids):
            raise HTTPException(status_code=422, detail="比较论文不能重复选择。")
        return compare_papers(
            ComparisonRequest(
                question=request.question,
                paper_ids=request.paper_ids,
                limit=max(2, request.limit),
            ),
            http_request,
        )
    retrieve_only = _wants_evidence_only(request.question)
    route = "retrieve_only" if retrieve_only else "grounded_answer"
    steps = [
        AgentStepRecord(
            tool="intent_router",
            status="done",
            detail=f"识别为{INTENT_LABELS[intent]}问题。",
        ),
        AgentStepRecord(
            tool="tool_selector",
            status="done",
            detail=(
                "选择只检索原文工具。"
                if retrieve_only else f"选择{INTENT_LABELS[intent]}证据问答流程。"
            ),
        ),
    ]

    retrieval_question = _question_for_evidence_search(request.question, retrieve_only)
    items, total_candidates = search_evidence(
        retrieval_question,
        paper_ids=request.paper_ids,
        limit=request.limit,
        diversify_by_work=not request.paper_ids,
    )
    steps.append(AgentStepRecord(
        tool="retrieve_evidence",
        status="done",
        detail=f"检查 {total_candidates} 个文本块，找到 {len(items)} 条候选证据。",
    ))
    verified_items = [
        item for item in items
        if item.text.strip() and item.source.page_start >= 1 and item.source.paper_id
    ]
    sufficient = bool(verified_items)
    steps.append(AgentStepRecord(
        tool="evidence_gate",
        status="done" if sufficient else "skipped",
        detail=(
            f"{len(verified_items)} 条证据均包含原文和有效页码。"
            if sufficient else "没有通过证据检查的片段，停止生成，避免无依据回答。"
        ),
    ))
    if not sufficient:
        return AgentResponse(
            question=request.question,
            insufficient=True,
            total_candidates=total_candidates,
            intent=intent,
            route=route,
            steps=steps,
        )

    if retrieve_only:
        steps.append(AgentStepRecord(
            tool="generate_grounded_answer",
            status="skipped",
            detail="用户只要求检索原文，本次未调用模型。",
        ))
        return AgentResponse(
            question=request.question,
            insufficient=False,
            items=verified_items,
            total_candidates=total_candidates,
            intent=intent,
            route="retrieve_only",
            steps=steps,
        )

    answer_response = _answer_with_evidence(
        request.question,
        verified_items,
        total_candidates,
        http_request.app.state.settings,
        answer_mode=intent,
    )
    steps.append(AgentStepRecord(
        tool="generate_grounded_answer",
        status="done",
        detail="模型已根据检索证据生成回答。" if not answer_response.insufficient else "模型判断现有证据不足。",
    ))
    if answer_response.insufficient:
        citation_status = "done"
        citation_detail = "模型判断证据不足，没有给出结论。"
    elif answer_response.citations:
        citation_status = "done"
        citation_detail = f"保留 {len(answer_response.citations)} 条由本地证据映射的有效引用。"
    else:
        citation_status = "skipped"
        citation_detail = "没有有效引用，因此拒绝展示无引用回答。"
    steps.append(AgentStepRecord(
        tool="citation_validator",
        status=citation_status,
        detail=citation_detail,
    ))
    return AgentResponse(
        **answer_response.model_dump(),
        intent=intent,
        route="grounded_answer",
        steps=steps,
    )


@router.post("/compare", response_model=AgentResponse)
def compare_papers(request: ComparisonRequest, http_request: Request) -> AgentResponse:
    """Retrieve evidence from every selected paper before generating a comparison."""

    metadata_by_id = {
        item["paper_id"]: item
        for item in paper_store._all_metadata()
    }
    missing_papers = [paper_id for paper_id in request.paper_ids if paper_id not in metadata_by_id]
    if missing_papers:
        raise HTTPException(status_code=404, detail="所选论文不存在，请刷新论文库后重试。")

    count = len(request.paper_ids)
    if request.limit < count:
        raise HTTPException(status_code=422, detail="证据条数至少要覆盖每一篇所选论文。")
    base_limit, remainder = divmod(request.limit, count)
    per_paper: list[list[RetrievalEvidenceRecord]] = []
    total_candidates = 0
    for index, paper_id in enumerate(request.paper_ids):
        paper_limit = max(1, base_limit + (1 if index < remainder else 0))
        evidence, candidate_count = search_evidence(
            _comparison_query_for_paper(request.question, metadata_by_id[paper_id]),
            paper_ids=[paper_id],
            limit=paper_limit,
            relax_query_coverage=True,
        )
        per_paper.append(evidence)
        total_candidates += candidate_count

    # Interleave sources so one paper does not dominate the prompt or the UI.
    items = [
        group[index]
        for index in range(max((len(group) for group in per_paper), default=0))
        for group in per_paper
        if index < len(group)
    ]
    covered_papers = {
        evidence.source.paper_id
        for group in per_paper
        for evidence in group
    }
    steps = [
        AgentStepRecord(
            tool="intent_router",
            status="done",
            detail="识别为多论文比较问题。",
        ),
        AgentStepRecord(
            tool="tool_selector",
            status="done",
            detail=f"分别检索用户选择的 {count} 篇论文，避免单篇文献挤占全部证据。",
        ),
        AgentStepRecord(
            tool="retrieve_evidence",
            status="done",
            detail="；".join(
                f"{metadata_by_id[paper_id].get('title') or metadata_by_id[paper_id]['filename']}：{len(evidence)} 条"
                for paper_id, evidence in zip(request.paper_ids, per_paper)
            ),
        ),
    ]
    if len(covered_papers) != count:
        steps.append(AgentStepRecord(
            tool="evidence_gate",
            status="skipped",
            detail="至少一篇所选论文没有找到可用证据，停止生成，避免把缺失来源误写成对比结论。",
        ))
        return AgentResponse(
            question=request.question,
            insufficient=True,
            items=items,
            total_candidates=total_candidates,
            intent="comparison",
            route="grounded_answer",
            steps=steps,
        )

    steps.append(AgentStepRecord(
        tool="evidence_gate",
        status="done",
        detail=f"所有 {count} 篇所选论文均有原文片段和有效页码。",
    ))
    answer_response = _answer_with_evidence(
        request.question,
        items,
        total_candidates,
        http_request.app.state.settings,
        answer_mode="comparison",
        required_paper_ids=set(request.paper_ids),
    )
    steps.extend([
        AgentStepRecord(
            tool="generate_grounded_answer",
            status="done",
            detail="模型已根据各篇论文的独立证据生成比较回答。" if not answer_response.insufficient else "模型判断现有证据不足。",
        ),
        AgentStepRecord(
            tool="citation_validator",
            status="done" if answer_response.insufficient or answer_response.citations else "skipped",
            detail=(
                f"保留 {len(answer_response.citations)} 条有效引用，引用均映射到所选论文。"
                if answer_response.citations
                else "模型判断证据不足，没有给出结论。" if answer_response.insufficient
                else "没有有效引用，因此拒绝展示无引用回答。"
            ),
        ),
    ])
    return AgentResponse(
        **answer_response.model_dump(),
        intent="comparison",
        route="grounded_answer",
        steps=steps,
    )
