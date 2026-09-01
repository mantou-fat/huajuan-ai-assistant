@echo off
rem Start Huajuan (Huaman Flower) Flask server, skip if already running
netstat -ano | findstr /c:":5000 " | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    exit /b 0
)
cd /d D:\python
"D:\minicoda\envs\ai_study\python.exe" app.py >> D:\python\huajuan.log 2>&1
