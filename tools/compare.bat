@echo off
cd /d "%~dp0"

if "%~1"=="" (
    echo Cover / Stego comparison tool
    echo.
    echo Usage:
    echo   compare.bat ^<cover image^> ^<stego image^> [--out dir] [--gain 20]
    echo.
    echo Example:
    echo   compare.bat testing\cover.png output\stego.png
    echo.
    echo Reports MSE / PSNR / changed-pixel ratio, and writes a side-by-side
    echo comparison image into output\compare\.
    pause
    exit /b 0
)
".venv\Scripts\python.exe" compare.py %*
if errorlevel 1 pause
