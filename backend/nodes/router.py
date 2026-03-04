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
    #    - router는 JSON만 필요하므로, 채팅 말풍선에는 내용을 스트리밍하지 않는다(q=None).
    full_response = await stream_llm_and_collect(None, msgs)

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

    # 5. SSE로 router reason 전송 (UI에는 사람 읽기 좋은 형태로만 노출, 사회자 말풍선은 사용하지 않음)
    if q and (next_node or reason):
        # next_node를 사람이 이해하기 쉬운 라벨로 치환
        role_label_map = {
            "tech": "기술 전문가",
            "business": "사업 전문가",
            "economy": "경제 전문가",
            "estimate": "정리 및 견적서",
        }
        display_next = role_label_map.get(next_node, (next_node or "").strip() or "?")
        display_text = f"다음 발언자: {display_next}"
        if reason:
            display_text += f"\n이유: {reason}"

        # 우측 패널(사회자 reason 영역)에만 표시
        await q.put({"router_reason": display_text, "next_node": next_node})

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
    #    - router의 JSON 응답은 messages에 넣지 않아 전문가에게 그대로 노출되지 않도록 한다.
    return {
        "previous_node": "router",
        "router_next_node": next_node,
        "called_tech_node": tech_count,
        "called_business_node": biz_count,
        "called_economy_node": eco_count,
    }


def after_router(state: AgentState, config) -> str:
    """
    router 이후 다음 노드를 결정.
    - 시간 제한을 넘기면 무조건 stop(그래프 종료).
    - 아니면 router_node 가 state["router_next_node"] 에 기록해 둔 값을 기반으로
      tech / business / economy 중 하나를 선택.
    """
    if time_limit_reached(state, config):
        # 그래프를 종료하고, 이후 외부 Estimator 에이전트가 정리를 담당
        return "stop"

    next_node = (state.get("router_next_node") or "").strip().lower()
    if next_node in ("tech", "business", "economy"):
        return next_node

    # fallback: 알 수 없으면 tech 로 시작
    return "tech"

