"""유틸 함수 (메시지·시간·그래프 config 등)."""
import contextvars
import time
import asyncio
from typing import Optional, List
from pdf2image import convert_from_path
from io import BytesIO
import base64

from langchain_core.messages import HumanMessage
from backend.models.llm import llm
from backend.models import AgentState

try:
    # PDF를 페이지별 이미지로 변환하기 위한 선택적 의존성
    from pdf2image import convert_from_bytes  # type: ignore
except Exception:  # pragma: no cover - 선택적 의존성
    convert_from_bytes = None

try:
    # PDF에서 텍스트를 추출하기 위한 선택적 의존성
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - 선택적 의존성
    pdfplumber = None

# LangGraph 노드에 config가 안 넘어갈 때 쓰는 폴백 (streaming에서 set)
config_ctx: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("graph_config", default=None)


def get_config(cfg: Optional[dict]) -> dict:
    """노드에 전달된 config 또는 config_ctx에 저장된 config 반환. configurable이 있으면 그대로, 없으면 ctx에서 읽음."""
    if cfg and isinstance(cfg, dict) and cfg.get("configurable"):
        return cfg
    return config_ctx.get() or {}


def time_limit_reached(state: dict, config: dict = None) -> bool:
    """설정 시간 초과 여부. state 또는 config.configurable의 start_time·time_limit_minutes 사용."""
    start = state.get("start_time")
    limit_m = state.get("time_limit_minutes")
    
    if start is None or limit_m is None:
        cfg = (config or {}).get("configurable") if isinstance(config, dict) else {}
        cfg = cfg if isinstance(cfg, dict) else {}
        start = start if start is not None else cfg.get("start_time", 0)
        limit_m = limit_m if limit_m is not None else cfg.get("time_limit_minutes", 1)

    return (time.time() - start) >= (limit_m * 60)


def message_content_to_str(content) -> str:
    """메시지 content(문자열 또는 블록 리스트)를 평문 문자열로 변환."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "\n".join(
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )

    return str(content or "")


def conversation_to_text(state: AgentState) -> str:
    """state.messages를 [사용자]/[AI] 태그가 포함된 단일 텍스트로 변환."""
    conv_text = []
    for m in state.get("messages", []):
        tag = "[사용자]" if isinstance(m, HumanMessage) else "[AI]"
        conv_text.append(f"{tag}\n{message_content_to_str(getattr(m, 'content', ''))}")
    return "\n\n---\n\n".join(conv_text)


def get_run_context(config: dict):
    """
    노드 실행 시 공통으로 사용하는 run_config 정보에서
    SSE 큐(queue)와 prompts 설정을 꺼내온다.
    """
    cfg = get_config(config or {})
    configurable = cfg.get("configurable", {}) or {}
    q = configurable.get("queue")
    prompts_cfg = configurable.get("prompts", {}) or {}
    return q, prompts_cfg


def append_last_message_summary(state: AgentState, prompt_text: str) -> str:
    """
    state의 마지막 메시지를 텍스트로 풀어서
    '이전 대화 내용' 섹션으로 프롬프트에 붙인다.
    """
    last_content = (
        message_content_to_str(getattr(state["messages"][-1], "content", ""))
        if state.get("messages")
        else ""
    )
    if last_content.strip():
        prompt_text += "\n\n이전 대화 내용:\n" + last_content.strip()
    return prompt_text


async def stream_llm_and_collect(q, msgs) -> str:
    """
    공통 LLM 호출 함수.
    - msgs를 llm.astream(...)으로 스트리밍 호출
    - 토큰을 모두 이어붙여 하나의 문자열로 반환
    - SSE 큐(q)가 있으면 토큰을 그대로 흘려보낸다.
    """

    full_response = ""
    async for chunk in llm.astream(msgs):
        if chunk.content:
            piece = str(chunk.content)
            if q:
                await q.put(piece)
            full_response += piece
    return full_response


def pdf_to_images(pdf_path, dpi=200):
    # 1. PDF 전체 페이지를 이미지 리스트로 변환
    images = convert_from_path(pdf_path, dpi=dpi)
    base64_pages = []
    
    for img in images:
        buffered = BytesIO()
        img.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        base64_pages.append(img_str)
        
    return base64_pages


def pdf_to_text(pdf_bytes: bytes, max_pages: int = 10) -> str:
    """
    PDF 바이트에서 텍스트를 추출하여 하나의 문자열로 반환.
    - pdfplumber가 있으면 페이지별 텍스트를 뽑아 상위 max_pages 페이지만 사용.
    - 없거나 오류가 나면 빈 문자열을 반환 (PDF 텍스트는 생략).
    """
    if not pdfplumber:
        return ""

    try:
        text_chunks: List[str] = []
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    text_chunks.append(page_text)
        return "\n\n---\n\n".join(text_chunks).strip()
    except Exception:
        return ""