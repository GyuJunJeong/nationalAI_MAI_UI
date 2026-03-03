"""Flask 서버: UI 제공. 실시간 스트리밍은 FastAPI(8000) /negotiate 호출."""
from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def index():
    """루트 경로: index.html 템플릿 렌더링 (협상 UI)."""
    return render_template("index.html")


if __name__ == "__main__":
    # FastAPI(8000)와 충돌하지 않게 5000번 포트. 디버그 시 두 서버 모두 실행.
    app.run(port=5000, debug=True)
