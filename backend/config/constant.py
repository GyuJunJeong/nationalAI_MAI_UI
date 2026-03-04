"""설정 상수 및 기본 프롬프트 정의."""

from backend.prompts.tech import TECH_PROMPT
from backend.prompts.business import BUSINESS_PROMPT
from backend.prompts.economy import ECONOMY_PROMPT

# -----------------------------------------------------------------------------
# 경로·실행 설정
# -----------------------------------------------------------------------------
LLM_MODEL = "maternion/mai-ui:8b" # ahmadwaqar/mai-ui:8b
LLM_TEMPERATURE = 0.2

# 협상·스트리밍
DEFAULT_TIME_LIMIT_MINUTES = 1.0   # 협상 대화 기본 제한 시간(분)
TIME_LIMIT_MIN_FLOOR = 0.1         # time_limit_minutes 최소값
SSE_QUEUE_POLL_TIMEOUT = 0.05      # SSE 스트림에서 큐 get 대기 타임아웃(초)

# -----------------------------------------------------------------------------
# 기본 프롬프트
# -----------------------------------------------------------------------------
DEFAULT_PROMPTS = {
    "tech": TECH_PROMPT,
    "business": BUSINESS_PROMPT,
    "economy": ECONOMY_PROMPT,
}