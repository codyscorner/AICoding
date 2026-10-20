@echo off
cd /d "%~dp0"

echo Building Image People Sorter...
echo.

pyinstaller ImagePeopleSorter.spec --noconfirm

if errorlevel 1 (
    echo.
    echo Build FAILED. Press any key to close.
    pause >nul
    exit /b 1
)

echo.
echo Build complete. Copying to Apps folder...

set "DEST=P:\Apps\AICoded\Image People Sorter"
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /Y /Q "dist\ImagePeopleSorter\*" "%DEST%\"

echo.
echo Done. Output: %DEST%
echo.
pause
