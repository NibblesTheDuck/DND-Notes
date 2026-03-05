@echo off
title D&D Notes

:: Check Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Python is not installed or not in PATH.
    echo.
    echo  Download it from:  https://python.org
    echo  During install, check the box: "Add Python to PATH"
    echo  Then restart your PC and double-click this file again.
    echo.
    pause
    exit /b 1
)

:: Install Flask if not already present (Flask powers the web UI)
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installing web server (one-time, takes a moment)...
    python -m pip install flask --quiet
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: Could not install Flask. Check your internet connection.
        echo.
        pause
        exit /b 1
    )
)

echo  Starting D^&D Notes... your browser will open in a moment.
echo  Keep this window open while using the app.
echo.

python "%~dp0app.py"

echo.
echo  Server stopped. Press any key to close.
pause >nul
