@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found: %PY%
  pause
  exit /b 1
)

echo Running backend smoke test (real covers, real roundtrip)...
echo.
"%PY%" tests\smoke_test.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [OK] smoke test passed
) else (
  echo [FAIL] smoke test failed, code %RC%
)
pause
exit /b %RC%
