@echo off
REM Build ComfyUI Workflow Editor EXE with the shared AICoding venv and copy it to P:\Apps\AICoded.
cd /d "%~dp0"
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" build_exe.py
) else (
    python build_exe.py
)
pause
