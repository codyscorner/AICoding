@echo off
:: build.bat
:: Builds ComfyUI_Video_Creator (one-folder: EXE + _internal) and deploys it to
:: P:\Apps\AICoded\ComfyUI Video Creator. Close the app first.
::
:: Always builds with the repo .venv when it exists (PyQt6, requests,
:: websocket-client, Pillow, PyInstaller all live there).

cd /d "%~dp0"

echo === ComfyUI Video Creator EXE Builder ===
echo Working directory: %CD%
echo.

if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" build_exe.py
) else (
    python build_exe.py
)

if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Check output above.
    pause
    exit /b 1
)

echo.
pause
