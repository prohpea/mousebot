@echo off
cd /d "%~dp0"

echo ========================================
echo    CVM Single-EXE Builder
echo ========================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

venv\Scripts\python.exe -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [*] Installing PyInstaller...
    venv\Scripts\pip.exe install pyinstaller
)

echo [*] Building standalone single-file CVM.exe...
venv\Scripts\python.exe -m PyInstaller --clean --noconfirm CVM.spec

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
