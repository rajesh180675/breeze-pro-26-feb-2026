@echo off
:: Breeze Options Trader PRO v10.0 — Windows Launcher
echo ==========================================
echo  Breeze Options Trader PRO v10.0
echo ==========================================

if exist venv\Scripts\activate (
    call venv\Scripts\activate
)

if not exist data mkdir data
if not exist logs mkdir logs

echo Starting app on http://localhost:8501
streamlit run app.py --server.port 8501 --browser.gatherUsageStats false
pause
