@echo off
REM Run ComfyUI Workflow Editor from source, from wherever run.bat is called.
cd /d "%~dp0"

REM Prefer the shared AICoding venv; fall back to python on PATH.
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" main.py %*
) else (
    python main.py %*
)
if errorlevel 1 pause
