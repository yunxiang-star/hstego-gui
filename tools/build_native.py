# -*- coding: utf-8 -*-
"""手工构建 hstego 的两个原生扩展 (Windows / MSVC)。

不依赖 setuptools 定位 VS（那条路径会调用被安全策略拦截的 reg.exe），
而是直接把 MSVC + Windows SDK 的 include/lib 路径拼出来交给 cl.exe。
"""
import os, sys, glob, io, subprocess

LOG = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\build_native_log.txt"
SRC = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\hstego-src"
PYINC = r"C:\Users\ILLENIUM\.workbuddy\binaries\python\versions\3.13.12\include"
VSDIR = r"C:\Program Files\Microsoft Visual Studio\18\Community"

log = []
def p(s=""):
    log.append(str(s))

# ---- 1. 定位 MSVC 工具集 ----
msvc_roots = glob.glob(os.path.join(VSDIR, "VC", "Tools", "MSVC", "*"))
msvc_roots = [d for d in msvc_roots if os.path.isdir(os.path.join(d, "include"))]
msvc = sorted(msvc_roots)[-1] if msvc_roots else None
p("MSVC: %s" % msvc)

cl = None
if msvc:
    for cand in ("Hostx64\\x64", "Hostx64\\x86", "Hostx86\\x64"):
        cx = os.path.join(msvc, "bin", cand, "cl.exe")
        if os.path.exists(cx):
            cl = cx
            break
p("cl.exe: %s" % cl)

# ---- 2. 定位 Windows SDK ----
kits = r"C:\Program Files (x86)\Windows Kits\10"
sdk = None
sdk_includes, sdk_libs = [], []
inc_root = os.path.join(kits, "Include")
if os.path.isdir(inc_root):
    for v in sorted(os.listdir(inc_root), reverse=True):
        u = os.path.join(inc_root, v, "ucrt")
        if os.path.isdir(u):
            sdk = v
            sdk_includes = [u,
                            os.path.join(inc_root, v, "um"),
                            os.path.join(inc_root, v, "shared"),
                            os.path.join(inc_root, v, "winrt")]
            break
if sdk:
    lib_root = os.path.join(kits, "Lib", sdk)
    sdk_libs = [os.path.join(lib_root, "ucrt", "x64"),
                os.path.join(lib_root, "um", "x64")]
p("Windows SDK: %s" % sdk)

if not cl or not sdk:
    p("FATAL: toolchain not located")
    with io.open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    sys.exit(1)

# ---- 3. 组装环境 ----
env = dict(os.environ)
PYLIBS = os.path.join(os.path.dirname(PYINC), "libs")
p("PYLIBS exists: %s" % os.path.isdir(PYLIBS))

inc = [os.path.join(msvc, "include")] + [d for d in sdk_includes if os.path.isdir(d)] + [PYINC]
lib = [os.path.join(msvc, "lib", "x64")] + [d for d in sdk_libs if os.path.isdir(d)]
if os.path.isdir(PYLIBS):
    lib.append(PYLIBS)
env["INCLUDE"] = ";".join(inc)
env["LIB"] = ";".join(lib)
env["PATH"] = os.path.dirname(cl) + os.pathsep + env.get("PATH", "")
p("INCLUDE: " + env["INCLUDE"])
p("LIB: " + env["LIB"])

# ---- 4. 编译 ----
def build(tag, sources, extra, outname):
    cmd = [cl, "/nologo", "/LD", "/O2"] + extra + sources + ["/Fe:" + outname]
    p("")
    p("=== %s ===" % tag)
    p("CMD: " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=SRC, env=env, capture_output=True, text=True,
                       errors="replace")
    p(r.stdout or "")
    p(r.stderr or "")
    p("EXIT=%d" % r.returncode)
    return r.returncode == 0 and os.path.exists(os.path.join(SRC, outname))

ok_stc = build("BUILD STC",
               ["src\\common.cpp", "src\\stc_embed_c.cpp", "src\\stc_extract_c.cpp",
                "src\\stc_interface.cpp", "src\\stc_ml_c.cpp"],
               ["/EHsc", "/I", "src", "/I", PYINC],
               "hstego_stc_extension.so")

UCRT_IMPORT = os.path.join(kits, "Lib", sdk, "ucrt", "x64", "ucrt.lib")
p("UCRT import lib: %s (exists=%s)" % (UCRT_IMPORT, os.path.exists(UCRT_IMPORT)))

ok_jpg = build("BUILD JPEG TOOLBOX",
               ["src\\jpeg_toolbox_extension.c",
                "src\\jpeg-9c-win\\Lib\\static_x64\\jpeg.lib",
                UCRT_IMPORT,
                "legacy_stdio_definitions.lib"],
               ["/I", "src\\jpeg-9c-win\\Include",
                "/NODEFAULTLIB:libucrt", "/NODEFAULTLIB:libcmt",
                "/NODEFAULTLIB:msvcrt", "/DEFAULTLIB:ucrt.lib"],
               "hstego_jpeg_toolbox_extension.so")

p("")
p("STC OK: %s   JPEG OK: %s" % (ok_stc, ok_jpg))
p("FILES: " + repr(sorted(os.path.basename(x) for x in glob.glob(os.path.join(SRC, "*.so")) +
                          glob.glob(os.path.join(SRC, "*.dll")))))

with io.open(LOG, "w", encoding="utf-8") as f:
    f.write("\n".join(log))
print("done")
