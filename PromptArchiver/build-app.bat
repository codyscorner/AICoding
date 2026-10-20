@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: build-app.bat — Build PromptArchiver.exe with PyInstaller
::
:: Uses the shared AICoding venv (..\\.venv). The spec file excludes the
:: venv's heavy ML packages so the EXE stays small.
:: Output: dist\PromptArchiver.exe  → copied to P:\Apps\AICoded\Prompt Archiver\
:: ─────────────────────────────────────────────────────────────────────────────
cd /d "%~dp0"

set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo ERROR: shared venv not found at %VENV_PY%
    pause
    exit /b 1
)

echo [1/3] Verifying PyInstaller...
"%VENV_PY%" -m pip install pyinstaller --quiet

echo [2/3] Running PyInstaller...
"%VENV_PY%" -m PyInstaller PromptArchiver.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. Check output above.
    pause
    exit /b 1
)

echo [3/3] Deploying to P:\Apps\AICoded\Prompt Archiver\ ...
if not exist "P:\Apps\AICoded\Prompt Archiver" mkdir "P:\Apps\AICoded\Prompt Archiver"
copy /Y "dist\PromptArchiver.exe" "P:\Apps\AICoded\Prompt Archiver\PromptArchiver.exe"

echo.
echo Done: P:\Apps\AICoded\Prompt Archiver\PromptArchiver.exe
pause
