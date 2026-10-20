@echo off
rem Run PDF Edit from source (uses the AICoding venv)
cd /d "%~dp0"
"P:\AI\AICoding\.venv\Scripts\python.exe" main.py %*
if errorlevel 1 pause
