@echo off
cd /d C:\Users\TeamOS\Desktop\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot
venv\Scripts\python.exe -m unittest tests/test_detection_perf_budget.py > C:\test_out.txt 2>&1
