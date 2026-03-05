@echo off
title Building DnD Notes.exe...
echo.
echo  ==========================================
echo   Building DnD Notes.exe  (run this once)
echo  ==========================================
echo.

:: Check Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found. Install from https://python.org
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: Install PyInstaller
echo  Installing PyInstaller...
python -m pip install pyinstaller --quiet
if %errorlevel% neq 0 (
    echo  ERROR: Could not install PyInstaller.
    pause
    exit /b 1
)

:: Build the exe
echo  Building exe (takes about 30-60 seconds)...
echo.
python -m PyInstaller --onefile --windowed --name "DnD Notes" --icon="%~dp0icon.ico" "%~dp0launcher.py"
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Build failed. See output above.
    pause
    exit /b 1
)

:: Move exe here and clean up
move /Y "%~dp0dist\DnD Notes.exe" "%~dp0DnD Notes.exe" >nul
rmdir /S /Q "%~dp0dist" 2>nul
rmdir /S /Q "%~dp0build" 2>nul
del /Q "%~dp0DnD Notes.spec" 2>nul

echo.
echo  ==========================================
echo   Done!  "DnD Notes.exe" is ready.
echo.
echo   You can now delete:
echo     - build.bat  (this file)
echo     - launcher.py
echo     - Launch DnD Notes.bat
echo  ==========================================
echo.
pause
