## NationalAI 검증 에이전트

여러 명의 전문가 에이전트(기술·사업·경제)가 사용자의 요구사항과 첨부 파일(PDF/이미지)을 함께 보고 토론한 뒤, 최종 **정리 및 견적서**를 만들어 주는 데모 애플리케이션입니다.  
프로젝트 루트에 있는 **`demo.mp4`** 를 열어 실제 동작 데모를 바로 확인할 수 있습니다. (`[데모 영상 보기](./demo.mp4)`)

백엔드는 `backend/` 디렉터리의 **FastAPI + LangGraph + LangChain(Ollama)**, 프론트엔드는 `frontend/` 디렉터리의 **Flask + Jinja 템플릿(단일 HTML)** 구조로 되어 있습니다.

---

### 실행 명령어

- **권장: FastAPI + Flask를 한 번에 실행 (Windows PowerShell)**

```bash
cd c:\nationalAI\project
.\run_both.ps1
```

`run_both.ps1` 은 두 개의 파워쉘 창을 열어 아래 두 서버를 동시에 실행합니다.

- FastAPI (백엔드 API / SSE 스트리밍):

```bash
python -m uvicorn backend.app_fastapi:app --port 8000
```

- Flask (프론트엔드 UI):

```bash
python -m flask --app frontend.app_flask run --port 5000 --debug
```

- **수동 실행 (플랫폼 공통 예시)**

```bash
cd c:\nationalAI\project

# 1) FastAPI (API 서버, 8000번 포트)
uvicorn backend.app_fastapi:app --port 8000

# 2) Flask (UI 서버, 5000번 포트)
python -m flask --app frontend.app_flask run --port 5000 --debug
```

브라우저 접속:
- UI: `http://localhost:5000`
- API 상태 확인: `http://localhost:8000`

---

### backend 전체 구조

- **FastAPI 진입점 (`backend/app_fastapi.py`)**
  - `/api/prompts` : 서버 기본 시스템 프롬프트(tech/business/economy)를 반환.
  - `/negotiate` :  
    - 폼 데이터로 **prompt / image(PDF 또는 이미지 1개) / time_minutes / 각 전문가 프롬프트**를 받습니다.
    - PDF인 경우 `backend.utils.utils.pdf_to_text` 로 텍스트를 추출해 사용자 프롬프트 뒤에 붙입니다.
    - 이미지인 경우 base64 한 장을 생성해 최초 `HumanMessage` 에 이미지 블록으로 포함합니다.
  - 실제 그래프 실행과 SSE 응답은 `backend.utils.streaming.event_generator` 에 위임합니다.

- **스트리밍 & 초기 상태 (`backend/utils/streaming.py`)**
  - `build_initial_state_and_config(prompt, images_b64, prompts, time_limit_minutes, q)`  
    - 텍스트 + 이미지(base64)를 LangChain `HumanMessage` 의 `content` 리스트로 구성.
    - `start_time`, `time_limit_minutes`, 에이전트별 프롬프트, SSE 큐(`asyncio.Queue`)를 포함한 `initial_state`, `run_config` 를 생성합니다.
  - `event_generator(...)`  
    - `graph.ainvoke(initial_state, run_config)` 를 비동기로 실행하고,
    - 큐에 들어오는 토큰을 `data: {...}\n\n` 형식의 SSE로 내보냅니다.
    - 마지막에 `estimate_result`(최종 견적 마크다운)과 `[DONE]` 이벤트를 전송합니다.

- **그래프 & 노드 (`backend/models/graph.py`, `backend/nodes/*.py`)**
  - `backend.models.state.AgentState`  
    - LangGraph 전체에서 공유하는 상태 타입으로,
      - `messages`: LangChain 메시지 리스트
      - `estimate_result`: 최종 견적 마크다운 문자열
      - `start_time`, `time_limit_minutes`: 대화 시간 관리용
      - `previous_node`: 직전 노드 이름
      - `called_tech_node`, `called_business_node`, `called_economy_node`: 각 전문가 호출 횟수
      - `router_next_node`: 라우터가 선택한 다음 노드 이름  
    를 포함합니다.

  - **그래프 정의 (`backend/models/graph.py`)**
    - `StateGraph(AgentState)` 기반 허브-스포크 구조:
      - 노드:
        - `router` : 다음에 어떤 전문가를 부를지 결정하는 사회자 노드.
        - `tech` : 기술 전문가 노드.
        - `business` : 사업 전문가 노드.
        - `economy` : 경제/재무 전문가 노드.
        - `estimate` : 전체 대화를 보고 최종 마크다운 견적서를 생성하는 노드.
      - 엣지:
        - 엔트리 포인트는 항상 `router`.
        - `router` → (조건부) `tech` / `business` / `economy` / `estimate`
        - `tech` / `business` / `economy` → 다시 `router` (턴을 반복)
        - `estimate` → `END` (그래프 종료)
      - 조건부 엣지 함수 `after_router(state, config)`:
        - `time_limit_reached(...)` 가 `True` 이면 강제로 `"estimate"` 로 전환.
        - 그렇지 않으면 `state["router_next_node"]` 값(tech/business/economy/estimate)에 따라 다음 노드를 결정.
        - 유효하지 않은 값이면 기본값으로 `"tech"` 사용.

  - **전문가 노드 (`backend/nodes/expert.py`)**
    - 공통 구현 `run_expert_node(...)`:
      - `get_run_context(config)` 로 SSE 큐와 사용자 커스텀 프롬프트를 꺼냅니다.
      - 역할별 기본 시스템 프롬프트(예: `backend.prompts.tech.TECH_PROMPT`)와 사용자가 수정한 프롬프트를 합쳐 `SystemMessage` 를 구성합니다.
      - **그래프 첫 `HumanMessage`** (사용자 텍스트 + 첨부 이미지 블록)을 찾아 모든 전문가 호출에서 항상 동일하게 참조합니다.
      - `backend.utils.utils.stream_llm_and_collect` 로 `llm.astream(...)` 을 호출해 토큰을 모두 이어 붙인 뒤, 하나의 `AIMessage` 로 `state["messages"]` 에 추가합니다.
    - `tech_expert`, `business_expert`, `economy_expert` 는 모두 위 공통 로직을 역할/프롬프트만 다르게 호출합니다.
    - `estimate_node`:
      - `conversation_to_text(state)` 로 전체 대화를 한국어 태그(`[사용자]`, `[AI]`)가 포함된 단일 문자열로 만들고,
      - `backend.prompts.estimator.ESTIMATE_PROMPT` + 사용자의 전체 대화를 입력으로 하여 **마크다운 형식의 정리 및 견적서**를 생성합니다.
      - 스트리밍 중간 결과는 `{"estimate_stream": ...}` 이벤트로, 최종 결과는 `state["estimate_result"]` 로 저장됩니다.

  - **라우터 노드 (`backend/nodes/router.py`)**
    - `conversation_to_text(state)` 로 지금까지의 전체 대화를 텍스트로 압축합니다.
    - `backend.prompts.router.ROUTER_PROMPT` + `ADD_PROMPT` 에
      - `conversation_history`
      - `previous_node`
      - 각 전문가 호출 횟수(`called_*_node`)
      를 주입해 LLM에 전달합니다.
    - LLM 응답은 JSON 문자열(`{"next_node": "...", "reason": "..."}`) 형식으로 받고:
      - `next_node` → `state["router_next_node"]` 및 호출 횟수 증가.
      - `reason` → SSE 이벤트 `{"router_reason": ..., "next_node": ...}` 로 프론트엔드 우측 상단에 표시.

- **모델 정의 (`backend/models/llm.py`)**
  - `from backend import config` 를 통해:
    - `LLM_MODEL = "maternion/mai-ui:8b"`
    - `LLM_TEMPERATURE = 0.3`
    를 가져와 `ChatOllama` 기반 `llm` 인스턴스 생성.

- **환경 설정 & 프롬프트 (`backend/config/*.py`, `backend/prompts/*.py`)**
  - `backend/config/constant.py`
    - 모델/스트리밍 관련 상수: `LLM_MODEL`, `LLM_TEMPERATURE`, `DEFAULT_TIME_LIMIT_MINUTES`, `TIME_LIMIT_MIN_FLOOR`, `SSE_QUEUE_POLL_TIMEOUT`.
    - 기본 프롬프트 묶음: `DEFAULT_PROMPTS = {"tech": ..., "business": ..., "economy": ...}`.
  - `backend/config/__init__.py`
    - 상수와 `TECH_PROMPT`, `BUSINESS_PROMPT`, `ECONOMY_PROMPT` 를 재노출하여 `import backend.config as config` 패턴을 지원.
  - `backend/prompts/tech.py`, `business.py`, `economy.py`
    - 각 전문가 역할에 맞는 한글 시스템 프롬프트 정의.
  - `backend/prompts/estimator.py`
    - 전체 대화 요약 + 마크다운 견적서 작성을 위한 프롬프트.
  - `backend/prompts/router.py`
    - 다음 발언자 선택을 위한 라우터 프롬프트와, 대화 히스토리/이전 노드/호출 횟수 등을 설명하는 추가 지시문 템플릿.

- **유틸리티 (`backend/utils/utils.py`)**
  - `config_ctx` / `get_config` / `get_run_context` : LangGraph 노드에서 공통 실행 설정(`queue`, `prompts`, 시간 정보 등)을 꺼내 쓰기 위한 헬퍼.
  - `time_limit_reached(state, config)` : 시작 시각과 제한 시간(분)을 기준으로 대화 시간 초과 여부 판정.
  - `message_content_to_str(...)`, `conversation_to_text(...)` : LangChain 메시지들을 사람이 읽기 좋은 한글 태그 포함 문자열로 변환.
  - `stream_llm_and_collect(q, msgs)` : 공통 LLM 스트리밍 호출 유틸.
  - `pdf_to_text(pdf_bytes, max_pages=10)` : `pdfplumber` 가 설치되어 있으면 상위 N페이지에서 텍스트를 추출해 하나의 문자열로 병합.

---

### frontend 구조

- **Flask 서버 (`frontend/app_flask.py`)**
  - 루트(`/`) 요청에 대해 `templates/index.html` 을 렌더링.
  - FastAPI(8000)와 포트가 겹치지 않도록 5000번 포트에서 동작.

- **단일 HTML UI (`frontend/templates/index.html`)**
  - 4단계 탭 구조:
    1. **입력·첨부** – 요구사항 텍스트, 파일 첨부(PDF/이미지), 미리보기.
    2. **프롬프트 편집** – 기술/사업/경제 전문가 프롬프트를 수정. 비우면 `/api/prompts` 응답을 기본값으로 사용.
    3. **대화** – SSE로 들어오는 토큰을 역할별 말풍선으로 스트리밍 표시.
    4. **정리 및 견적서** – `estimate_stream` / `estimate` 이벤트를 받아 `marked@12` UMD 빌드로 마크다운을 렌더링.
  - JavaScript에서 `API_BASE = 'http://localhost:8000'` 로 FastAPI 서버와 통신합니다.

---

### 설치 요약

- **필수**
  - Python 3.10 이상
  - [Ollama](https://ollama.com/) 설치 및 `maternion/mai-ui:8b` 모델 pull
  - 필수 패키지 예시:

```bash
pip install fastapi "uvicorn[standard]" flask langchain-ollama langgraph pdfplumber
```

- **선택 (PDF를 페이지 이미지로 쓰고 싶을 경우만)**  
  - `pdf2image` + Poppler (현재 코드는 텍스트 추출 위주이므로 필수는 아님).

환경이나 모델 이름은 `backend/config/constant.py` 를 수정해 프로젝트에 맞게 조정할 수 있습니다.

