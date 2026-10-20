@echo off
REM Build ComfyUI Metadata Viewer with PyInstaller (one-file EXE) and deploy it to
REM P:\Apps\AICoded\ComfyUI Metadata Viewer\
REM
REM Uses the shared AICoding venv (..\.venv). The spec file excludes the venv's heavy
REM ML packages so the EXE stays small. Bump the version in comfyui_metadata_viewer.py
REM (and CHANGELOG.md) before building.
cd /d "%~dp0"

set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
set "DEPLOY=P:\Apps\AICoded\ComfyUI Metadata Viewer"

if not exist "%VENV_PY%" (
    echo ERROR: shared venv not found at %VENV_PY%
    pause
    exit /b 1
)

echo [1/3] Verifying PyInstaller...
"%VENV_PY%" -m pip install pyinstaller --quiet

echo [2/3] Running PyInstaller...
"%VENV_PY%" -m PyInstaller ComfyUI_Metadata_Viewer.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. Check output above.
    pause
    exit /b 1
)

echo [3/3] Deploying to %DEPLOY% ...
if not exist "%DEPLOY%" mkdir "%DEPLOY%"
copy /Y "dist\ComfyUI_Metadata_Viewer.exe" "%DEPLOY%\" >nul
if errorlevel 1 (
    echo.
    echo ERROR: deploy copy failed - is the app still running?
    pause
    exit /b 1
)

echo.
echo Done: %DEPLOY%\ComfyUI_Metadata_Viewer.exe
pause
