"""전문가 노드 정의 (tech / business / economy / estimate)."""
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from backend.models import AgentState
from backend.models.llm import llm
from backend.prompts import tech as tech_prompts
from backend.prompts import business as business_prompts
from backend.prompts import economy as economy_prompts
from backend.prompts import estimator as estimator_prompts
from backend.utils.utils import get_run_context, stream_llm_and_collect, conversation_to_text


async def run_expert_node(
    state: AgentState,
    config: dict,
    *,
    role: str,
    prompt_key: str,
    default_prompt: str,
) -> dict:
    q, prompts_cfg = get_run_context(config)

    if q:
        await q.put({"role": role})

    base_prompt = (prompts_cfg.get(prompt_key) or "").strip() or default_prompt
    prompt_text = base_prompt

    # 초기 사용자 메시지(텍스트 + 이미지 블록)를 찾아 모든 전문가가 동일하게 참고하도록 포함
    initial_human = None
    for m in state.get("messages", []):
        if isinstance(m, HumanMessage):
            initial_human = m
            break

    msgs = [SystemMessage(content=prompt_text)]
    if initial_human is not None:
        msgs.append(initial_human)

    full_response = await stream_llm_and_collect(q, msgs)

    return {
        "messages": [AIMessage(content=full_response)],
        "previous_node": role,
    }


async def tech_expert(state: AgentState, config: dict = None):
    """기술 전문가 노드."""
    return await run_expert_node(
        state,
        config,
        role="tech",
        prompt_key="tech",
        default_prompt=tech_prompts.TECH_PROMPT,
    )


async def business_expert(state: AgentState, config: dict = None):
    """사업 전문가 노드."""
    return await run_expert_node(
        state,
        config,
        role="business",
        prompt_key="business",
        default_prompt=business_prompts.BUSINESS_PROMPT,
    )


async def economy_expert(state: AgentState, config: dict = None):
    """경제 전문가 노드."""
    return await run_expert_node(
        state,
        config,
        role="economy",
        prompt_key="economy",
        default_prompt=economy_prompts.ECONOMY_PROMPT,
    )


async def estimate_node(state: AgentState, config: dict = None) -> dict:
    """전체 대화를 요약·정리하여 견적서를 생성하는 노드."""
    q, _ = get_run_context(config)

    if q:
        await q.put({"estimate_status": "running"})

    full_conv = conversation_to_text(state)

    msgs = [
        SystemMessage(content=estimator_prompts.ESTIMATE_PROMPT),
        HumanMessage(content=full_conv),
    ]

    # ESTIMATE는 클라이언트에 중간 누적본을 계속 보내야 하므로,
    # _stream_llm_and_collect 대신 이 노드만 전용 스트리밍 루프를 유지한다.
    estimate_text = ""
    async for chunk in llm.astream(msgs):
        if chunk.content:
            piece = str(chunk.content)
            estimate_text += piece
            if q:
                await q.put({"estimate_stream": estimate_text})

    # 최종 턴은 estimate 노드가 수행했음을 기록
    return {
        "estimate_result": estimate_text,
        "previous_node": "estimate",
    }