@echo off
chcp 65001 >nul
cd /d %~dp0
echo [밤길 안심 예보관] 실행 준비
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate
  python -m pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)
if not exist .env copy .env.example .env >nul
python -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
pause
