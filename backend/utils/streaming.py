"""협상 그래프 실행 및 SSE 스트리밍 (graph와 분리)."""
import asyncio
import json
import time
from typing import Optional

from langchain_core.messages import HumanMessage

from backend import config
from backend.models.graph import graph
from backend.utils.utils import config_ctx


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
        "estimate_result": None,
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

    Args:
        prompt: 사용자 요구사항 텍스트.
        img_b64: 단일 이미지 base64 문자열 또는 None.
        prompts: 에이전트별 시스템 프롬프트 dict (tech, business, economy 키).
        time_limit_minutes: 대화 제한 시간(분). None이면 config.DEFAULT_TIME_LIMIT_MINUTES 사용.

    Yields:
        SSE 형식 문자열 ("data: {...}\n\n").
    """
    q = asyncio.Queue()

    initial_state, run_config = build_initial_state_and_config(
        prompt=prompt,
        images_b64=images_b64,
        prompts=prompts,
        time_limit_minutes=time_limit_minutes,
        q=q,
    )

    config_ctx.set(run_config)
    task = asyncio.create_task(graph.ainvoke(initial_state, run_config)) # graph.py 참고

    # 3. SSE 이벤트 스트림
    try:
        while True:
            try:
                token = await asyncio.wait_for(q.get(), timeout=config.SSE_QUEUE_POLL_TIMEOUT)
                yield f"data: {_sse_token(token)}\n\n"
            except asyncio.TimeoutError:
                if task.done():
                    while not q.empty():
                        try:
                            token = q.get_nowait()
                            yield f"data: {_sse_token(token)}\n\n"
                        except asyncio.QueueEmpty:
                            break
                    break

        # 4. 마지막 견적 결과 송출
        final = task.result()
        estimate = final.get("estimate_result") if isinstance(final, dict) else None
        if estimate is not None and (isinstance(estimate, str) and estimate.strip() or estimate):
            yield f"data: {json.dumps({'estimate': str(estimate).strip()}, ensure_ascii=False)}\n\n"

        yield "data: " + json.dumps({"t": "[DONE]"}) + "\n\n"

    finally:
        if not task.done():
            task.cancel()
