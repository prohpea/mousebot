@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo    CVM colorBot Setup Script
echo ========================================
echo.

if exist "runtime\Scripts\python.exe" (
    echo [*] Checking bundled runtime\ environment...
    "runtime\Scripts\python.exe" -c "import cv2, numpy, customtkinter, serial, abcurves_native; print('[OK] Bundled runtime verified: all core modules loaded.')"
    if not errorlevel 1 (
        echo.
        echo ========================================
        echo    Setup Complete! Ready to launch.
        echo ========================================
        echo.
        echo Run run.bat to start CVM colorBot.
        echo.
        pause
        exit /b 0
    )
    echo [WARN] Bundled runtime\ check failed, falling back to venv setup...
    echo.
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.11 from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [*] Checking Python version...
python --version

if exist "venv\Scripts\python.exe" (
    echo [*] Virtual environment already exists, skipping creation
) else (
    echo [*] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created successfully
)

echo [*] Upgrading pip...
"venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

if exist "requirements.txt" (
    echo [*] Installing dependencies...
    if exist "wheels" (
        "venv\Scripts\python.exe" -m pip install -r requirements.txt --find-links wheels
    ) else (
        "venv\Scripts\python.exe" -m pip install -r requirements.txt
    )
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed successfully
) else (
    echo [WARNING] requirements.txt not found
)

echo.
echo ========================================
echo    Setup Complete!
echo ========================================
echo.
echo You can now run run.bat to start the program
echo.
pause
