@echo off
:: build.bat
:: Builds ComfyUI_Chain_Automator.exe with PyInstaller and deploys to
:: P:\Apps\AICoded\ComfyUI Chain Automator (skips deploy if the EXE there is in use)
::
:: Always builds with the repo .venv when it exists: the EXE must bundle
:: boto3 (LoRA pod check), which the system Python does not have.

cd /d "%~dp0"

echo === ComfyUI Chain Automator EXE Builder ===
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
