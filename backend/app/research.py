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
    RetrievalEvidenceRecord,
    RetrievalRequest,
    RetrievalResponse,
)
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


def _answer_with_evidence(
    question: str,
    items: list[RetrievalEvidenceRecord],
    total_candidates: int,
    settings: Settings,
    answer_mode: str = "general",
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
    insufficient = answer.strip().rstrip("。") == "当前资料不足"
    if not insufficient and not citations:
        raise HTTPException(status_code=502, detail="DeepSeek 回答未包含有效证据引用，请重试。")
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
