@echo off
rem Huajuan one-click restart (ASCII only, to avoid cmd encoding issues)
cd /d D:\python

echo [Huajuan] stopping old process on port 5000 ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":5000 .*LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)

timeout /t 1 /nobreak >nul

echo [huajuan-start] %date% %time% >> D:\python\huajuan.log
echo [Huajuan] starting...
"D:\minicoda\envs\ai_study\python.exe" app.py >> D:\python\huajuan.log 2>&1
