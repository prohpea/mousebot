@echo off
setlocal EnableExtensions
pushd "%~dp0"

title CVM colorBot Launcher

echo ========================================
echo       CVM colorBot Launcher
echo ========================================
echo.

:: 1. Kiem tra xem virtual environment co the khoi dong va load binary module (cv2) binh thuong khong
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import cv2" >nul 2>&1
    if not errorlevel 1 goto :launch_venv
)

:: 2. Neu venv gap loi Windows DLL initialization (0xC0000142), kiem tra fallback qua Python 64-bit he thong
if exist "venv\Lib\site-packages" (
    python -c "import sys; exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>&1
    if not errorlevel 1 goto :launch_sys
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

:: Kiem tra lai sau khi setup
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import cv2" >nul 2>&1
    if not errorlevel 1 goto :launch_venv
)
goto :launch_sys

:launch_venv
echo [*] Dang khoi dong CVM colorBot (Virtual Environment)...
echo.
"venv\Scripts\python.exe" main.py
goto :check_exit

:launch_sys
echo [*] Dang khoi dong CVM colorBot (Native 64-bit Python)...
echo.
set "PYTHONPATH=%~dp0venv\Lib\site-packages;%PYTHONPATH%"
python main.py
goto :check_exit

:check_exit
set "EXIT_CODE=%ERRORLEVEL%"
if %EXIT_CODE% neq 0 (
    echo.
    echo [ERROR] Ung dung ket thuc voi ma loi %EXIT_CODE%.
    pause
)

popd
exit /b %EXIT_CODE%
