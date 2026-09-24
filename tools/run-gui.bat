@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" hstego.py
if errorlevel 1 (
    echo.
    echo [Startup failed] See the error above.
    pause
)
