"""FastAPI 진입점 (backend/config, backend/utils, backend/models 사용)."""
import base64
from typing import Annotated, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from backend import config
from backend.utils.streaming import event_generator


app = FastAPI(title="AI 견적 협상 서버")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/prompts")
async def get_prompts():
    """에이전트별 기본 프롬프트를 반환 (프론트엔드 프롬프트 편집 탭 초기화용)."""
    return {
        "tech": config.TECH_PROMPT,
        "business": config.BUSINESS_PROMPT,
        "economy": config.ECONOMY_PROMPT,
    }


@app.post("/negotiate")
async def negotiate(
    prompt: Annotated[Optional[str], Form()] = None,
    time_minutes: Annotated[Optional[float], Form()] = 1.0,
    image: Optional[UploadFile] = File(None),
    prompt_tech: Annotated[Optional[str], Form()] = None,
    prompt_business: Annotated[Optional[str], Form()] = None,
    prompt_economy: Annotated[Optional[str], Form()] = None,
):
    """협상 스트리밍을 시작. 요구사항·파일·프롬프트·시간제한을 받아 event_generator로 SSE 스트리밍 응답."""
    # 요구사항 텍스트 정규화
    prompt = (prompt or "").strip()

    # 이미지 / PDF 처리:
    # - 이미지: 1장을 base64로 인코딩해 전달
    # - PDF: 텍스트를 추출해 prompt 뒤에 붙이고, 이미지는 보내지 않음
    images_b64: list[str] = []
    if image and image.filename:
        raw_bytes = await image.read()
        content_type = (image.content_type or "").lower()
        filename = (image.filename or "").lower()

        if content_type == "application/pdf" or filename.endswith(".pdf"):
            from backend.utils.utils import pdf_to_text

            pdf_text = pdf_to_text(raw_bytes)
            if pdf_text:
                if prompt:
                    prompt = f"{prompt}\n\n[첨부 PDF 내용]\n{pdf_text}"
                else:
                    prompt = f"[첨부 PDF 내용]\n{pdf_text}"
            images_b64 = []
        else:
            images_b64 = [base64.b64encode(raw_bytes).decode("utf-8")]

    # 에이전트별 프롬프트 (비어 있으면 서버 기본값)
    prompts = {
        "tech": (prompt_tech or "").strip() or config.DEFAULT_PROMPTS["tech"],
        "business": (prompt_business or "").strip() or config.DEFAULT_PROMPTS["business"],
        "economy": (prompt_economy or "").strip() or config.DEFAULT_PROMPTS["economy"],
    }

    # 대화 시간 제한(분) 파싱, 기본 1분
    try:
        time_limit = max(0.1, float(time_minutes)) if time_minutes not in (None, "") else 1.0
    except (TypeError, ValueError):
        time_limit = 1.0

    return StreamingResponse(
        event_generator(prompt, images_b64, prompts, time_limit_minutes=time_limit),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/", response_class=HTMLResponse)
async def root():
    """루트 경로: API 서버 상태 안내 HTML 반환."""
    return "<h1>AI 견적 협상 API 서버 가동 중</h1><p>POST /negotiate 를 통해 협상을 시작하세요.</p>"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
