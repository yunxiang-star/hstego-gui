@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found:
  echo         %PY%
  echo         Create it first, see webapp\README.md
  pause
  exit /b 1
)

set "HOST=127.0.0.1"
set "PORT=8000"

echo.
echo  HStego Web API
echo  ---------------------------------------------
echo   UI  (users)    : http://%HOST%:%PORT%/
echo   API (developers): http://%HOST%:%PORT%/docs
echo   Health check : http://%HOST%:%PORT%/api/v1/health
echo   Stop         : Ctrl+C
echo  ---------------------------------------------
echo.

"%PY%" -m backend --host %HOST% --port %PORT% %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] server exited with code %RC%
  pause
)
exit /b %RC%
