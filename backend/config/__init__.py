"""config 패키지 초기화.

외부에서는 기존처럼:

    import config
    config.LLM_MODEL

형태로 사용할 수 있도록, 실제 상수 정의는 `config.constant`와
`prompts.*` 모듈에 두고 여기서는 필요한 심볼을 재노출(re-export)한다.
"""

from .constant import (  # noqa: F401
    LLM_MODEL,
    LLM_TEMPERATURE,
    DEFAULT_TIME_LIMIT_MINUTES,
    TIME_LIMIT_MIN_FLOOR,
    SSE_QUEUE_POLL_TIMEOUT,
    DEFAULT_PROMPTS,
)

# 에이전트별 기본 프롬프트 (프롬프트 편집 탭에서 사용)
from backend.prompts.tech import TECH_PROMPT    # noqa: F401,E402
from backend.prompts.business import BUSINESS_PROMPT  # noqa: F401,E402
from backend.prompts.economy import ECONOMY_PROMPT    # noqa: F401,E402


