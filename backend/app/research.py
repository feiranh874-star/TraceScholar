"""Research retrieval and evidence-grounded answer endpoints."""

import re

from fastapi import APIRouter, HTTPException, Request

from app.llm import LLMServiceError, generate_grounded_answer
from app.models import AnswerCitationRecord, AnswerResponse, RetrievalRequest, RetrievalResponse
from app.retrieval import search_evidence


router = APIRouter(prefix="/api/research", tags=["research"])


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

    settings = http_request.app.state.settings
    if not all((settings.llm_base_url, settings.llm_api_key, settings.llm_model)):
        raise HTTPException(
            status_code=503,
            detail="模型服务尚未配置，请设置 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY。",
        )
    try:
        answer = generate_grounded_answer(
            request.question,
            items,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
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
        question=request.question,
        answer=answer,
        insufficient=insufficient,
        provider=settings.llm_provider or "deepseek",
        model=settings.llm_model,
        citations=citations,
        items=items,
        total_candidates=total_candidates,
    )
