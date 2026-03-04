ROUTER_PROMPT = (
    """당신은 사회자 역할을 수행하는 전문가입니다. 이전 대화 내용을 바탕으로 다음 대화 흐름을 결정하세요. 답변은 JSON 형식으로 반환하세요.
"""
)

ADD_PROMPT1 = (
    """
# 이전 대화 내용
{conversation_history}

# 이전 발언 노드
{previous_node}

# 호출된 노드 개수
# "tech": {tech_node}, "business": {business_node}, "economy": {economy_node}

# Output Format (JSON)
{{
    "next_node": "string (e.g., tech, business, economy)",
    "reason": "string (3~5문장 이내의 이유 설명)"
}}

# 참고 사항
- 이전 발언 노드는 가장 최근 대화 발언을 한 노드이고, next_node 로는 갈 수 없습니다.
- reason 은 next_node 로 설정한 이유에 대해서 설명하세요.
- 호출된 노드 개수가 최대한 고르게 반영해주세요.
"""
)

ADD_PROMPT = ADD_PROMPT1