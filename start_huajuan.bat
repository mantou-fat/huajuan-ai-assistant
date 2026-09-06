@echo off
rem ============================================================
rem  Huajuan one-click restart (一键重启)
rem  Double-click this ANY time - also after code changes:
rem   1) kills the old process listening on port 5000
rem   2) starts the server fresh (logs -> huajuan.log)
rem  Close this window to stop the server.
rem ============================================================
cd /d D:\python

echo [Huajuan] stopping old process on port 5000 ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":5000 .*LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)

timeout /t 1 /nobreak >nul

echo [Huajuan] starting...
"D:\minicoda\envs\ai_study\python.exe" app.py >> D:\python\huajuan.log 2>&1
