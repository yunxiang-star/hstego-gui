@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Rebuilding HStego C extensions
echo ============================================================
echo.

set "VCVARS="

rem --- 1) locate Visual Studio via vswhere (works for any version) ---
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "!VSWHERE!" (
    for /f "usebackq delims=" %%i in (`"!VSWHERE!" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2^>nul`) do (
        if exist "%%i\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%i\VC\Auxiliary\Build\vcvars64.bat"
    )
)

rem --- 2) fall back to well-known install paths ---
if not defined VCVARS (
    for %%d in (
        "%ProgramFiles%\Microsoft Visual Studio\18\Community"
        "%ProgramFiles%\Microsoft Visual Studio\18\BuildTools"
        "%ProgramFiles%\Microsoft Visual Studio\2022\Community"
        "%ProgramFiles%\Microsoft Visual Studio\2022\Professional"
        "%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise"
        "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools"
        "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools"
    ) do (
        if exist "%%~d\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%~d\VC\Auxiliary\Build\vcvars64.bat"
    )
)

if not defined VCVARS (
    echo [ERROR] vcvars64.bat not found.
    echo.
    echo   Install Visual Studio Build Tools with the
    echo   "Desktop development with C++" workload, then retry.
    echo.
    pause
    exit /b 1
)

echo Using: !VCVARS!
echo.

call "!VCVARS!" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to initialise the MSVC environment.
    pause
    exit /b 1
)

echo Compiling...
echo.
".venv\Scripts\python.exe" setup-win.py build_ext --inplace
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed, see the messages above.
    pause
    exit /b 1
)

echo.
echo Build finished. Updated .so files are in this folder.
pause
