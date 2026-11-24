@echo off
cd /d "%~dp0"

echo ========================================
echo    CVM Single-EXE Builder
echo ========================================
echo.

set "PYTHON_EXE="
if exist "runtime\Scripts\python.exe" (
    set "PYTHON_EXE=runtime\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [*] Installing PyInstaller...
    "%PYTHON_EXE%" -m pip install pyinstaller
)

echo [*] Building standalone single-file CVM.exe...
"%PYTHON_EXE%" -m PyInstaller --clean --noconfirm CVM.spec

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo ========================================
echo    Build Complete!
echo    Output: dist\CVM.exe
echo ========================================
echo.
pause
