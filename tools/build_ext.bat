@echo off
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
cd /d "C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\hstego-src"

set PYINC=C:\Users\ILLENIUM\.workbuddy\binaries\python\versions\3.13.12\include
if not exist "%PYINC%\Python.h" (
  echo PYINC-MISSING: %PYINC%
  dir "C:\Users\ILLENIUM\.workbuddy\binaries\python\versions\3.13.12" /b
)

echo === BUILD STC ===
cl /nologo /LD /O2 /EHsc /I src /I "%PYINC%" src\common.cpp src\stc_embed_c.cpp src\stc_extract_c.cpp src\stc_interface.cpp src\stc_ml_c.cpp /Fe:hstego_stc_extension.so
echo STC_EXIT=%ERRORLEVEL%

echo === BUILD JPEG TOOLBOX ===
cl /nologo /LD /O2 /I src\jpeg-9c-win\Include src\jpeg_toolbox_extension.c src\jpeg-9c-win\Lib\static_x64\jpeg.lib /Fe:hstego_jpeg_toolbox_extension.so
echo JPEG_EXIT=%ERRORLEVEL%

echo === RESULT FILES ===
dir /b *.so *.dll *.lib
