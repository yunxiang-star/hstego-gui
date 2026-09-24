@echo off
cd /d "%~dp0"

if not exist "output" mkdir "output"

if "%~1"=="" (
    echo HStego command line
    echo.
    echo Usage:
    echo   run-cli.bat embed   ^<msg file^> ^<cover image^> ^<stego image^> [password]
    echo   run-cli.bat extract ^<stego image^> ^<output msg file^> [password]
    echo   run-cli.bat capacity ^<image^> [--raw]
    echo.
    echo Examples:
    echo   run-cli.bat capacity testing\cover.png
    echo   run-cli.bat embed testing\input-secret.txt testing\cover.png output\stego.png MyP4ssw0rd101
    echo   run-cli.bat extract output\stego.png output\msg.txt MyP4ssw0rd101
    echo.
    echo Notes:
    echo   - The output\ folder is created automatically.
    echo   - If embed fails, run "capacity" first: the message must fit in the
    echo     cover. A JPEG cover holds far less than a PNG one.
    echo   - Omit [password] and you will be prompted, the input is hidden.
    echo.
    echo To open the graphical interface, run: run-gui.bat
    pause
    exit /b 0
)
".venv\Scripts\python.exe" hstego.py %*
if errorlevel 1 pause
