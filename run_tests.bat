@echo off
setlocal
cd /d "%~dp0"

set PYTHONDONTWRITEBYTECODE=1

if exist "runtime\Scripts\python.exe" (
    set "PYTHON=runtime\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

"%PYTHON%" -B -m unittest discover -s tests -t . -v
exit /b %errorlevel%
