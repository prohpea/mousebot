@echo off
setlocal EnableExtensions
pushd "%~dp0"

title CVM colorBot Setup

echo ========================================
echo       CVM colorBot Setup
echo ========================================
echo.

:: 1. Tim trinh thong dich Python 64-bit hop le tren he thong
set "PY_EXE="
set "PY_ARGS="

:: Uu tien py -3-64 launcher
py -3-64 -c "import sys; exit(0 if (sys.version_info >= (3, 8) and sys.maxsize > 2**32) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3-64"
    goto :found_python
)

:: Kiem tra py launcher chung (64-bit)
py -3 -c "import sys; exit(0 if (sys.version_info >= (3, 8) and sys.maxsize > 2**32) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
    goto :found_python
)

:: Kiem tra lenh python trong PATH (64-bit)
python -c "import sys; exit(0 if (sys.version_info >= (3, 8) and sys.maxsize > 2**32) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=python"
    set "PY_ARGS="
    goto :found_python
)

:: Kiem tra cac duong dan cai dat mac dinh pho bien tren Windows (64-bit)
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python310\python.exe"
    "C:\Python311\python.exe"
    "C:\Python312\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist "%%~P" (
        "%%~P" -c "import sys; exit(0 if (sys.version_info >= (3, 8) and sys.maxsize > 2**32) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PY_EXE=%%~P"
            set "PY_ARGS="
            goto :found_python
        )
    )
)

:: Kiem tra xem co phai may chi dang cai Python 32-bit hay khong
py -3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if not errorlevel 1 goto :err_32bit
python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if not errorlevel 1 goto :err_32bit

:not_found
echo [ERROR] Khong tim thay Python 3.8+ hop le tren he thong
echo.
echo Vui long cai dat Python 3.10 hoac 3.11 64-bit tu: https://www.python.org/downloads/
echo Luu y: Khi cai dat, nho tick vao Add python.exe to PATH.
echo.
pause
popd
exit /b 1

:found_python
echo [*] Phat hien Python: "%PY_EXE%" %PY_ARGS%
"%PY_EXE%" %PY_ARGS% -c "import sys; print(f'    Phien ban: {sys.version}')"
echo.

:: Kiem tra kien truc 64-bit (bat buoc cho OpenCV, NumPy, SciPy, CyndiLib, Medius)
"%PY_EXE%" %PY_ARGS% -c "import sys; exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 goto :err_32bit

:: 2. Kiem tra va tao Virtual Environment
if not exist "venv" goto :create_venv
if not exist "venv\Scripts\python.exe" goto :recreate_venv
"venv\Scripts\python.exe" -c "import sys; exit(0 if sys.prefix != sys.base_prefix else 1)" >nul 2>&1
if not errorlevel 1 (
    echo [*] Virtual environment da ton tai va hop le tren may nay.
    goto :install_deps
)

:recreate_venv
echo [*] Phat hien virtual environment cu bi loi hoac copy tu may khac.
echo [*] Dang don dep de tao lai virtual environment moi.
rd /s /q "venv" >nul 2>&1

:create_venv
echo [*] Dang tao Virtual Environment moi venv.
"%PY_EXE%" %PY_ARGS% -m venv venv
if errorlevel 1 (
    echo.
    echo [ERROR] Khong the tao Virtual Environment
    pause
    popd
    exit /b 1
)
echo [OK] Da tao Virtual Environment thanh cong.
echo.

:install_deps
:: 3. Cai dat thu vien truc tiep qua venv\Scripts\python.exe
if not exist "requirements.txt" (
    echo [WARNING] Khong tim thay file requirements.txt.
    goto :done
)

if exist "wheels\*.whl" (
    echo [*] Phat hien goi offline wheels, dang cai dat offline sieu toc.
    "venv\Scripts\python.exe" -m pip install -r requirements.txt --no-index --find-links=wheels --prefer-binary
    if not errorlevel 1 goto :install_success
    echo [*] Goi offline khong khop voi phien ban Python, chuyen sang tai truc tiep tu PyPI.
)

echo [*] Dang nang cap pip va cai dat cac thu vien tu Internet qua PyPI.
"venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel --quiet --timeout 15 --retries 2 >nul 2>&1
"venv\Scripts\python.exe" -m pip install -r requirements.txt --prefer-binary --timeout 60 --retries 3 --trusted-host pypi.org --trusted-host files.pythonhosted.org
if errorlevel 1 goto :err_pip

:install_success
echo.
echo [OK] Da cai dat day du cac thu vien thanh cong.

:done
echo.
echo ========================================
echo       Cai dat hoan tat
echo ========================================
echo Bay gio ban co the chay run.bat de su dung chuong trinh.
echo.
popd
if "%~1"=="" pause
exit /b 0

:err_32bit
echo ========================================================
echo [ERROR] BAN DANG CAI PHIEN BAN PYTHON 32-BIT
echo ========================================================
echo Cac thu vien do hoa va AI gom OpenCV, NumPy, CyndiLib, SciPy
echo KHONG ho tro Python 32-bit va BAT BUOC phai chay tren 64-bit.
echo.
echo Huong dan khac phuc:
echo   1. Vao Windows Settings, chon Apps, go bo cai dat Python 32-bit.
echo   2. Truy cap: https://www.python.org/downloads/windows/
echo   3. Tai ban: Windows installer 64-bit - Khuyen nghi Python 3.11.9 64-bit.
echo   4. Khi cai dat, nho tick chon: Add python.exe to PATH.
echo ========================================================
echo.
pause
popd
exit /b 1

:err_pip
echo.
echo ========================================================
echo [ERROR] CAI DAT THU VIEN THAT BAI
echo ========================================================
echo Huong dan xu ly cac nguyen nhan pho bien:
echo 1. Python khong phai 64-bit hoac phien ban 3.13 chua tuong thich.
echo    Khuyen nghi cai dat: Python 3.11.9 64-bit.
echo 2. Mang Internet bi chan hoac timeout toi PyPI:
echo    Hay thu bat VPN, dung mang 4G, hoac doi DNS 8.8.8.8 / 1.1.1.1.
echo 3. Phuc hoi offline: copy thu muc wheels vao cung thu muc bot.
echo ========================================================
echo.
pause
popd
exit /b 1
