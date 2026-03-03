# 실시간 스트리밍 디버깅: Flask(UI) + FastAPI(API) 동시 실행
$proj = $PSScriptRoot
if (-not $proj) { $proj = Get-Location }

Write-Host "1) FastAPI (스트리밍 API): http://localhost:8000" -ForegroundColor Cyan
Write-Host "2) Flask (UI): http://localhost:5000" -ForegroundColor Green
Write-Host ""
# Windows에서 --reload 시 multiprocessing spawn 오류 방지: reload 없이 실행
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$proj'; python -m uvicorn backend.app_fastapi:app --port 8000"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$proj'; python -m flask --app frontend.app_flask run --port 5000 --debug"
