@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: build.bat — Build PhotoGallery with PyInstaller
::
:: Uses the shared AICoding venv (..\.venv). The spec file excludes the
:: venv's heavy ML packages so the build stays small.
:: One-folder build: dist\PhotoGallery\  → mirrored to P:\Apps\AICoded\PhotoGallery\
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
"%VENV_PY%" -m PyInstaller PhotoGallery.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. Check output above.
    pause
    exit /b 1
)

echo [3/3] Deploying to P:\Apps\AICoded\PhotoGallery\ ...
robocopy "dist\PhotoGallery" "P:\Apps\AICoded\PhotoGallery" /MIR /R:2 /W:2 /XF photo_gallery_config.json photo_gallery_ratings.json /NFL /NDL /NJH
if errorlevel 8 (
    echo.
    echo ERROR: deploy copy failed.
    pause
    exit /b 1
)

echo.
echo Done: P:\Apps\AICoded\PhotoGallery\PhotoGallery.exe
pause
