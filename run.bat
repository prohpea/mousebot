@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo    CVM colorBot Launcher
echo ========================================
echo.

set "PYTHON_EXE="
if exist "runtime\Scripts\python.exe" (
    set "PYTHON_EXE=runtime\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    echo [ERROR] No Python runtime found in runtime\ or venv\
    echo Please run setup.bat first or check runtime\pyvenv.cfg
    echo.
    pause
    exit /b 1
)

echo [*] Starting CVM colorBot with %PYTHON_EXE%...
echo.

"%PYTHON_EXE%" main.py
set "EXIT_CODE=%errorlevel%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Program exited with code %EXIT_CODE%
    pause
    exit /b %EXIT_CODE%
)
