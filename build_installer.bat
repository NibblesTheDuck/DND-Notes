@echo off
title Building DnD Notes Installer...

:: Make sure DnD Notes.exe exists first
if not exist "%~dp0DnD Notes.exe" (
    echo.
    echo  ERROR: "DnD Notes.exe" not found.
    echo  Run build.bat first to create it, then run this script.
    echo.
    pause
    exit /b 1
)

:: Find Inno Setup compiler
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe"       set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe

if "%ISCC%"=="" (
    echo.
    echo  Inno Setup is not installed.
    echo.
    echo  Download it free from:  https://jrsoftware.org/isdl.php
    echo  Install it, then run this script again.
    echo.
    pause
    exit /b 1
)

echo  Building DnDNotesSetup.exe...
echo.
"%ISCC%" "%~dp0setup.iss"

if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Installer build failed. See output above.
    echo.
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo   Done!  DnDNotesSetup.exe is ready.
echo.
echo   Share that single file with your friends.
echo   They double-click it, follow the wizard,
echo   and they're good to go.
echo  ==========================================
echo.
pause
