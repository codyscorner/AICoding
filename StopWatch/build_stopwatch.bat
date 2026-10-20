@echo off
:: build_stopwatch.bat
:: Builds StopWatch.exe with PyInstaller and deploys to P:\Apps\AICoded\StopWatch

set DEST=P:\Apps\AICoded\StopWatch
set SHORTCUT_DIR=C:\Users\cody\OneDrive\Desktop\Vibe Coded Apps

:: Switch to the folder containing this bat file
cd /d "%~dp0"

echo === StopWatch EXE Builder ===
echo Working directory: %CD%
echo.

:: Check for PyInstaller
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

:: Check for pygame
python -c "import pygame" >nul 2>&1
if errorlevel 1 (
    echo pygame not found. Installing...
    pip install pygame
)

echo Building EXE...
pyinstaller --onefile --windowed --name StopWatch --icon="app_icon.ico" --add-data "TimerChime.mp3;." --add-data "app_icon.ico;." --exclude-module pkg_resources --exclude-module setuptools --distpath "dist" --workpath "build" --specpath "." "stopwatch.py"

if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Check output above.
    pause
    exit /b 1
)

echo.
echo Build successful!
echo.

:: Deploy
echo Deploying to %DEST%...
if not exist "%DEST%" mkdir "%DEST%"
copy /y "dist\StopWatch.exe" "%DEST%\StopWatch.exe"
echo Deployed.

:: Update shortcut
echo Updating shortcut...
powershell -Command "$s=New-Object -ComObject WScript.Shell; $lnk=$s.CreateShortcut('%SHORTCUT_DIR%\StopWatch.lnk'); $lnk.TargetPath='%DEST%\StopWatch.exe'; $lnk.WorkingDirectory='%DEST%'; $lnk.Save()"
echo Shortcut updated.

echo.
echo === Done! StopWatch.exe is at %DEST%\StopWatch.exe ===
pause
