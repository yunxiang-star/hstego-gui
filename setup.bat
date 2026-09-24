@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ============================================================
rem  HStego workbench - one-click bootstrap (Windows)
rem
rem  This script rebuilds the whole working environment from
rem  this repository alone:
rem    1. clone upstream hstego  (daniellerch/hstego)
rem    2. drop in our prebuilt native extensions (.so)
rem    3. copy the web application in
rem    4. create a virtual environment
rem    5. install dependencies (Tsinghua PyPI mirror)
rem    6. verify the native extensions actually load
rem
rem  Nothing in this repo is modified. Everything is written to
rem  <repo>\hstego-runtime\ which is git-ignored.
rem ============================================================

set "ROOT=%~dp0"
set "TARGET=%ROOT%hstego-runtime"
set "UPSTREAM=https://github.com/daniellerch/hstego.git"
set "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"

echo.
echo ============================================================
echo  HStego workbench - bootstrap
echo  target : %TARGET%
echo ============================================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] git not found in PATH. Install Git for Windows first.
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH. Install Python 3.11+ first.
    pause
    exit /b 1
)

rem ---------- 1/6  upstream ----------
if exist "%TARGET%\hstegolib.py" (
    echo [1/6] upstream hstego already present - skipping clone
) else (
    echo [1/6] cloning upstream hstego ...
    if exist "%TARGET%" rmdir /s /q "%TARGET%"
    git clone --depth 1 "%UPSTREAM%" "%TARGET%"
    if errorlevel 1 (
        echo [ERROR] git clone failed. Check your network / proxy.
        pause
        exit /b 1
    )
)

rem ---------- 2/6  native extensions ----------
echo [2/6] installing prebuilt native extensions ...
copy /y "%ROOT%runtime\hstego_stc_extension.so" "%TARGET%\" >nul
if errorlevel 1 ( echo [ERROR] copy stc extension failed & pause & exit /b 1 )
copy /y "%ROOT%runtime\hstego_jpeg_toolbox_extension.so" "%TARGET%\" >nul
if errorlevel 1 ( echo [ERROR] copy jpeg extension failed & pause & exit /b 1 )

rem ---------- 2b  helper scripts from tools/ ----------
for %%f in (run-gui.bat run-cli.bat selftest.bat compare.bat build-ext.bat) do (
    if exist "%ROOT%tools\%%f" copy /y "%ROOT%tools\%%f" "%TARGET%\" >nul
)
for %%f in (selftest.py compare.py) do (
    if exist "%ROOT%tools\%%f" copy /y "%ROOT%tools\%%f" "%TARGET%\" >nul
)

rem ---------- 3/6  web application ----------
echo [3/6] copying the web application ...
if exist "%TARGET%\webapp" rmdir /s /q "%TARGET%\webapp"
xcopy /e /i /y /q "%ROOT%webapp" "%TARGET%\webapp" >nul
if errorlevel 1 ( echo [ERROR] xcopy webapp failed & pause & exit /b 1 )

rem ---------- 4/6  virtual environment ----------
echo [4/6] creating the virtual environment ...
if not exist "%TARGET%\.venv\Scripts\python.exe" (
    python -m venv "%TARGET%\.venv"
    if errorlevel 1 ( echo [ERROR] python -m venv failed & pause & exit /b 1 )
)

set "PY=%TARGET%\.venv\Scripts\python.exe"

rem ---------- 5/6  dependencies ----------
echo [5/6] installing dependencies from %MIRROR% ...
"%PY%" -m pip install --upgrade pip -q -i %MIRROR%
"%PY%" -m pip install -r "%ROOT%runtime\requirements-hstego.txt" -i %MIRROR%
if errorlevel 1 ( echo [ERROR] algorithm dependencies failed & pause & exit /b 1 )
"%PY%" -m pip install -r "%ROOT%webapp\requirements.txt" -i %MIRROR%
if errorlevel 1 ( echo [ERROR] web dependencies failed & pause & exit /b 1 )

rem ---------- 6/6  verify ----------
echo [6/6] verifying the native extensions load ...
"%PY%" -c "import ctypes; ctypes.CDLL(r'%TARGET%\hstego_stc_extension.so'); ctypes.CDLL(r'%TARGET%\hstego_jpeg_toolbox_extension.so'); print('    native extensions OK')"
if errorlevel 1 (
    echo [ERROR] the prebuilt extensions do not load on this machine.
    echo         Rebuild them with tools\build_jpeg_toolbox.py
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Done.
echo.
echo   web app   : %TARGET%\webapp\run-server.bat
echo               then open http://127.0.0.1:8000/
echo   desktop   : %TARGET%\run-gui.bat
echo   roundtrip : %TARGET%\selftest.bat
echo   smoke test: %TARGET%\webapp\run-test.bat
echo ============================================================
echo.
echo Note: extraction in the JPEG domain fails silently about 25%
echo       of the time upstream - the web app self-checks and
echo       retries automatically. See docs\03_*.md
echo.
pause
exit /b 0
