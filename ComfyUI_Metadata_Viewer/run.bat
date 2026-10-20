@echo off
REM Run ComfyUI Metadata Viewer from source, from wherever run.bat is called.
REM Optional: pass any ComfyUI output file (png, mp4, webp, json...) to open it on launch, e.g.  run.bat Test_files\MiniMax_H3_00008-audio.mp4
cd /d "%~dp0"

REM Prefer the shared AICoding venv; fall back to python on PATH.
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" comfyui_metadata_viewer.py %*
) else (
    python comfyui_metadata_viewer.py %*
)
if errorlevel 1 pause
