@echo off
:: build_todolist.bat
:: Builds TodoList.exe with PyInstaller and deploys to P:\Apps\VibeCoded\TodoList

set DEST=P:\Apps\VibeCoded\TodoList
set SHORTCUT_DIR=C:\Users\cody\OneDrive\Desktop\Vibe Coded Apps

:: Switch to the folder containing this bat file
cd /d "%~dp0"

echo === TodoList EXE Builder ===
echo Working directory: %CD%
echo.

:: Check for PyInstaller
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

:: Check for PyQt6
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo PyQt6 not found. Installing...
    pip install PyQt6
)

echo Building EXE...
pyinstaller --onefile --windowed --name TodoList --icon="app_icon.ico" --add-data "app_icon.ico;." --exclude-module pkg_resources --exclude-module setuptools --distpath "dist" --workpath "build" --specpath "." "todo.py"

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
copy /y "dist\TodoList.exe" "%DEST%\TodoList.exe"
echo Deployed.

:: Update shortcut
echo Updating shortcut...
powershell -Command "$s=New-Object -ComObject WScript.Shell; $lnk=$s.CreateShortcut('%SHORTCUT_DIR%\TodoList.lnk'); $lnk.TargetPath='%DEST%\TodoList.exe'; $lnk.WorkingDirectory='%DEST%'; $lnk.IconLocation='%DEST%\TodoList.exe,0'; $lnk.Save()"
echo Shortcut updated.

echo.
echo === Done! TodoList.exe is at %DEST%\TodoList.exe ===
pause
