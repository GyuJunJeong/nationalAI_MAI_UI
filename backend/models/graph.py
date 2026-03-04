"""그래프·노드 정의 (Hub-and-Spoke 자율 토론형 워크플로우).

이 그래프는 router와 세 전문가(tech/business/economy)의 토론만 담당하고,
최종 견적서 생성(estimator)은 그래프 외부에서 별도로 수행한다.
"""
from langgraph.graph import StateGraph, END

from backend.models.state import AgentState
from backend.nodes.router import router_node, after_router
from backend.nodes.expert import tech_expert, business_expert, economy_expert


# -----------------------------------------------------------------------------
# 그래프 빌드
# -----------------------------------------------------------------------------
def _build_workflow():
    """router에서 tech/business/economy로만 분기하는 협상 그래프를 빌드."""
    workflow = StateGraph(AgentState)

    workflow.add_node("router", router_node)
    workflow.add_node("tech", tech_expert)
    workflow.add_node("business", business_expert)
    workflow.add_node("economy", economy_expert)

    workflow.set_entry_point("router")

    # router에서 JSON(next_node, reason) 기반으로 분기 (시간 초과 시 END)
    workflow.add_conditional_edges(
        "router",
        after_router,
        {
            "tech": "tech",
            "business": "business",
            "economy": "economy",
            "stop": END,  # after_router가 "stop"을 반환하면 그래프 종료
        },
    )

    # 각 전문가 턴 이후에는 다시 router 로 돌아와 다음 턴을 결정
    workflow.add_edge("tech", "router")
    workflow.add_edge("business", "router")
    workflow.add_edge("economy", "router")
    return workflow.compile()


graph = _build_workflow()