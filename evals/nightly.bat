@echo off
cd /d D:\python
C:\Python314\python.exe evals\auto_all.py >> D:\python\evals\nightly.log 2>&1
C:\Python314\python.exe evals\monitor.py >> D:\python\evals\nightly.log 2>&1
