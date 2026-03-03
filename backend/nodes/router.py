"""Router 노드 정의 (대화 흐름 결정)."""
import json
from langchain_core.messages import AIMessage, SystemMessage

from backend.models import AgentState
from backend.prompts import router as router_prompts
from backend.utils.utils import (
    get_run_context,
    time_limit_reached,
    stream_llm_and_collect,
    conversation_to_text,
)


async def router_node(state: AgentState, config: dict = None) -> dict:
    """
    라우터 노드.
    - 전체 대화 내용을 텍스트로 모아 router 프롬프트(ROUTER_PROMPT + ADD_PROMPT)에 주입.
    - JSON 형태의 {"next_node": ..., "reason": ...} 응답을 파싱하여
      - SSE로 reason 이벤트 전송
      - state["router_next_node"]에 next_node 저장 (조건부 엣지에서 사용)
      - 각 노드 호출 횟수(called_*_node)를 갱신
    """
    q, prompts_cfg = get_run_context(config)

    if q:
        await q.put({"role": "router"})

    # 1. 이전 대화 전체 + 직전 노드 이름 준비
    conversation_history = conversation_to_text(state)
    previous_node = state.get("previous_node") or ""

    # 2. 프롬프트 구성 (커스텀 router 프롬프트가 있으면 우선 사용)
    base_prompt = (prompts_cfg.get("router") or "").strip() or router_prompts.ROUTER_PROMPT
    add_prompt = router_prompts.ADD_PROMPT.format(
        conversation_history=conversation_history,
        previous_node=previous_node,
        tech_node=state.get("called_tech_node") or "",
        business_node=state.get("called_business_node") or "",
        economy_node=state.get("called_economy_node") or "",
    )
    prompt_text = base_prompt + add_prompt

    msgs = [SystemMessage(content=prompt_text)]

    # 3. LLM 호출 및 응답 수집
    full_response = await stream_llm_and_collect(q, msgs)

    # 4. JSON 파싱 시도
    next_node = ""
    reason = ""
    try:
        data = json.loads(full_response.strip())
        if isinstance(data, dict):
            next_node = str(data.get("next_node", "")).strip()
            reason = str(data.get("reason", "")).strip()
    except Exception:
        # JSON 파싱 실패 시, 전체 응답을 reason 으로 간주하고 다음 노드는 공백으로 둔다.
        reason = full_response.strip()

    # 5. SSE로 router reason 전송
    if q and reason:
        await q.put({"router_reason": reason, "next_node": next_node})

    # 6. 선택된 노드에 대해서만 카운트 증가 로직
    tech_count = state.get("called_tech_node") or 0
    biz_count = state.get("called_business_node") or 0
    eco_count = state.get("called_economy_node") or 0

    if next_node == "tech":
        tech_count += 1
    elif next_node == "business":
        biz_count += 1
    elif next_node == "economy":
        eco_count += 1

    # 7. 상태 업데이트
    return {
        "messages": [AIMessage(content=full_response)],
        "previous_node": "router",
        "router_next_node": next_node,
        "called_tech_node": tech_count,
        "called_business_node": biz_count,
        "called_economy_node": eco_count,
    }


def after_router(state: AgentState, config) -> str:
    """
    router 이후 다음 노드를 결정.
    - 시간 제한을 넘기면 무조건 estimate.
    - 아니면 router_node 가 state["router_next_node"] 에 기록해 둔 값을 기반으로
      tech / business / economy / estimate 중 하나를 선택.
    """
    if time_limit_reached(state, config):
        return "estimate"

    next_node = (state.get("router_next_node") or "").strip().lower()
    if next_node in ("tech", "business", "economy", "estimate"):
        return next_node

    # fallback: 알 수 없으면 tech 로 시작
    return "tech"

