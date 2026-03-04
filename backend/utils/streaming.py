"""협상 그래프 실행 및 SSE 스트리밍 (graph와 분리).

역할 분리:
- LangGraph(graph)는 router + 세 전문가(tech/business/economy) 토론만 수행
- PDF 각 페이지별 토론 결과를 모아서,
  마지막에 단일 Estimator 에이전트에게 딕셔너리 형태로 전달해 최종 견적서를 생성
"""
import asyncio
import json
import time
from typing import Optional, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from backend import config
from backend.models.graph import graph
from backend.models.llm import llm
from backend.prompts import estimator as estimator_prompts
from backend.utils.utils import config_ctx, conversation_to_text


def _sse_token(token) -> str:
    """토큰을 SSE data 페이로드 문자열로 변환."""
    if isinstance(token, dict):
        return json.dumps(token, ensure_ascii=False)
    return json.dumps({"t": str(token)}, ensure_ascii=False)

def build_initial_state_and_config(
    prompt: str,
    images_b64: Optional[list[str]],
    prompts: dict,
    time_limit_minutes: Optional[float],
    q: asyncio.Queue,
):
    """
    사용자의 프롬프트와 옵션들을 받아서 그래프의 초기 상태(initial_state) 및 
    실행 환경(run_config)을 생성하는 함수.

    Args:
        prompt (str): 사용자 입력 텍스트 프롬프트.
        images_b64 (Optional[list[str]]): base64 인코딩 이미지 리스트 (첨부 없으면 None/빈 리스트).
        prompts (dict): 에이전트별 시스템 프롬프트 딕셔너리.
        time_limit_minutes (Optional[float]): 대화 제한 시간(분, None이면 기본값 사용).
        q (asyncio.Queue): SSE 토큰 전송용 큐.
    
    Returns:
        initial_state (dict): 그래프 엔트리 상태(메시지, 시간 등).
        run_config (dict): 에이전트 실행 환경(큐, 프롬프트, 시간 등 포함).
    """

    # 1. 메시지 컨텐츠 세팅: 텍스트 프롬프트와 이미지들(있으면)을 message로 포함
    content = [{"type": "text", "text": prompt}]
    for b64 in images_b64 or []:
        if not b64:
            continue
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            }
        )

    # 2. 시작 타임스탬프, 제한 시간 결정 (최소 시간 이상)
    start_ts = time.time()
    limit_m = max(
        config.TIME_LIMIT_MIN_FLOOR,
        float(time_limit_minutes if time_limit_minutes is not None else config.DEFAULT_TIME_LIMIT_MINUTES),
    )

    # 3. 그래프 초기 상태(state) 정의
    initial_state = {
        "messages": [HumanMessage(content=content)],
        "previous_node": None,  # 대화 시작 시 이전 노드는 없음
        "start_time": start_ts,
        "time_limit_minutes": limit_m,
    }

    # 4. 실행 환경(run_config) 정의: 큐/프롬프트/시간 등 런 기반 정보 전달
    run_config = {
        "configurable": {
            "queue": q,
            "prompts": prompts,
            "start_time": start_ts,
            "time_limit_minutes": limit_m,
        }
    }

    # 5. 상태 및 환경 반환
    return initial_state, run_config

async def event_generator(
    prompt: str,
    images_b64: Optional[list[str]],
    prompts: dict,
    time_limit_minutes: Optional[float] = None,
):
    """
    협상 그래프를 비동기 실행하고, 큐에서 이벤트를 꺼내 SSE 형식으로 yield하는 비동기 생성기.

    동작 개요:
    - images_b64가 여러 장이면 각 이미지를 한 페이지로 간주하여
      페이지별로 그래프(전문가 토론)를 독립 실행
    - 각 페이지별 대화 내용을 딕셔너리 {페이지키: 대화텍스트} 에 누적
    - 마지막에 Estimator 에이전트를 한 번 호출해, 모인 딕셔너리 정보를 기반으로 최종 견적서를 생성
    """
    q: asyncio.Queue = asyncio.Queue()

    # 페이지별 대화 내용 저장용 딕셔너리
    page_conversations: Dict[str, str] = {}

    # 이미지가 여러 장이면 각 이미지를 한 페이지로 보고 순회
    pages = images_b64 if images_b64 else [None]
    total_pages = len(pages)

    for idx, page_img in enumerate(pages, start=1):
        page_key = f"page_{idx}"

        # 현재 페이지/전체 페이지 정보를 SSE로 알림
        await q.put({"page_info": {"current": idx, "total": total_pages}})

        # 단일 페이지용 이미지 리스트 구성 (없으면 빈 리스트)
        page_images = [page_img] if page_img else []

        initial_state, run_config = build_initial_state_and_config(
            prompt=prompt,
            images_b64=page_images,
            prompts=prompts,
            time_limit_minutes=time_limit_minutes,
            q=q,
        )

        # 현재 페이지의 run_config를 컨텍스트에 설정
        config_ctx.set(run_config)
        task = asyncio.create_task(graph.ainvoke(initial_state, run_config))  # graph.py 참고

        # SSE 이벤트 스트림 (해당 페이지 토론 구간)
        try:
            while True:
                try:
                    token = await asyncio.wait_for(q.get(), timeout=config.SSE_QUEUE_POLL_TIMEOUT)
                    yield f"data: {_sse_token(token)}\n\n"
                except asyncio.TimeoutError:
                    if task.done():
                        # 남은 토큰 모두 비움
                        while not q.empty():
                            try:
                                token = q.get_nowait()
                                yield f"data: {_sse_token(token)}\n\n"
                            except asyncio.QueueEmpty:
                                break
                        break

            # 페이지별 최종 상태에서 대화 내용을 텍스트로 저장
            final_state = task.result()
            if isinstance(final_state, dict):
                try:
                    page_conversations[page_key] = conversation_to_text(final_state)
                except Exception:
                    # conversation_to_text 실패 시 해당 페이지는 건너뜀
                    pass

        finally:
            if not task.done():
                task.cancel()

    # --- 모든 페이지 토론 종료 후, 단일 Estimator 에이전트로 최종 견적 생성 ---

    # 페이지 대화가 전혀 없으면 견적 생성 단계는 생략
    if not page_conversations:
        yield "data: " + json.dumps({"t": "[DONE]"}) + "\n\n"
        return

    # 1) SSE로 estimate 시작 알림
    yield f"data: {json.dumps({'estimate_status': 'running'}, ensure_ascii=False)}\n\n"

    # 2) Estimator 에이전트 입력 텍스트 구성
    #    { "page_1": "...대화...", "page_2": "...대화..." } 형태를 사람이 읽기 쉬운 텍스트로 변환
    parts = []
    for k, v in page_conversations.items():
        parts.append(f"[페이지 {k}]\n{v}")
    full_conv_for_estimator = "\n\n---\n\n".join(parts).strip()

    msgs = [
        SystemMessage(content=estimator_prompts.ESTIMATE_PROMPT),
        HumanMessage(content=full_conv_for_estimator),
    ]

    # 3) Estimator LLM 스트리밍 호출 (중간 누적본을 계속 SSE로 전송)
    estimate_text = ""
    async for chunk in llm.astream(msgs):
        if chunk.content:
            piece = str(chunk.content)
            estimate_text += piece
            # 프론트의 정리·견적서 패널이 실시간으로 갱신되도록 전체 누적본을 보낸다.
            yield f"data: {json.dumps({'estimate_stream': estimate_text}, ensure_ascii=False)}\n\n"

    # 4) 최종 견적 결과 송출
    final_estimate = estimate_text.strip()
    if final_estimate:
        yield f"data: {json.dumps({'estimate': final_estimate}, ensure_ascii=False)}\n\n"

    # 5) 스트리밍 종료 마커
    yield "data: " + json.dumps({"t": "[DONE]"}) + "\n\n"
