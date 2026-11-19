@echo off
set "PYTHONPATH=%~dp0venv\Lib\site-packages;%PYTHONPATH%"
set "CVM_SKIP_PERF=1"
python -m unittest tests.test_ui_dpg tests.test_color_filter_anti_noise tests.test_windmouse_predictive
exit /b %ERRORLEVEL%
