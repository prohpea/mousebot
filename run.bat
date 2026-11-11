@echo off
setlocal EnableExtensions
pushd "%~dp0"

title CVM colorBot Launcher

echo ========================================
echo       CVM colorBot Launcher
echo ========================================
echo.

:: Kiem tra virtual environment co ton tai va hop le tren may nay khong
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys; exit(0 if sys.prefix != sys.base_prefix else 1)" >nul 2>&1
    if not errorlevel 1 goto :launch
)

echo [*] Virtual environment chua co hoac khong hop le tren may/duong dan nay.
echo [*] Dang tu dong goi setup.bat de thiet lap moi truong...
echo.

if exist "setup.bat" (
    call "setup.bat" --auto
    if errorlevel 1 (
        popd
        exit /b 1
    )
) else (
    echo [ERROR] Khong tim thay file setup.bat!
    pause
    popd
    exit /b 1
)

:launch
echo [*] Dang khoi dong CVM colorBot...
echo.
"venv\Scripts\python.exe" main.py

set "EXIT_CODE=%ERRORLEVEL%"
if %EXIT_CODE% neq 0 (
    echo.
    echo [ERROR] Ung dung ket thuc voi ma loi %EXIT_CODE%.
    pause
)

popd
exit /b %EXIT_CODE%
