"""AgentState 정의 (LangGraph 상태 타입)."""
from typing import Annotated, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """협상 그래프의 공유 상태. messages는 add_messages로 누적됨."""
    messages: Annotated[List[BaseMessage], add_messages]
    estimate_result: Optional[str]
    previous_node: Optional[str]
    router_next_node: Optional[str]
    start_time: Optional[float]  # 협상 시작 시각 (time.time())
    time_limit_minutes: Optional[float]  # 대화 제한 시간(분)
    called_tech_node: Optional[int]
    called_business_node: Optional[int]
    called_economy_node: Optional[int]

