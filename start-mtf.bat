@echo off
REM Double-click launcher for start-mtf.ps1 (local MTF research app).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-mtf.ps1" %*
echo.
pause
