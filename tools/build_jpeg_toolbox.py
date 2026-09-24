# -*- coding: utf-8 -*-
"""hstego JPEG Toolbox 扩展 —— Windows/MSVC 修复版构建脚本

【为什么要重写】
原 build_native.py 走的是「链接仓库自带的 jpeg.lib 静态库」这条路，失败根因：
  - src/jpeg-9c-win/Lib/static_x64/jpeg.lib 是别人用 MSVC 2017 编的，其 obj 里带着
    /DEFAULTLIB:libucrt（静态 UCRT）指令；
  - 而我们自己的扩展默认按 /MT(静态) 或显式 ucrt.lib(导入库) 链接，
    两套 CRT 同时进来 → LNK2005 重复定义(exit/fflush/__acrt_iob_func...) → LNK1169。
  - 更隐蔽的是：cl.exe 根本不认 /NODEFAULTLIB:xxx 这种写法（命令行报 D9002「忽略未知选项」），
    所以原脚本里那三个 /NODEFAULTLIB 从头到尾一个都没生效，等于白写。

【本脚本思路】
彻底不碰那个 jpeg.lib —— 仓库里其实带着完整 libjpeg 9c 源码
(src/jpeg-9c-win/jpeg-9c-src，46 个库源文件一个不缺)。
把 libjpeg 源码 + 扩展源码在同一次 cl 调用里一起编成一个 DLL，
于是全工程只有一套编译器和一套 CRT(/MD，与 CPython 一致)，CRT 冲突在物理上不可能发生。
仅需从 Include/ 借一个 jconfig.h(内容与 jconfig.vc 完全相同)。

不需要联网，不需要 MSYS2，不需要 WSL。
"""
import os
import sys
import glob
import io
import time
import subprocess

PROJ = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48"
SRC = os.path.join(PROJ, "hstego-src")
JPEG_WIN = os.path.join(SRC, "src", "jpeg-9c-win")
JPEG_SRC = os.path.join(JPEG_WIN, "jpeg-9c-src")
JPEG_INC = os.path.join(JPEG_WIN, "Include")
BUILD = os.path.join(SRC, "jpegbuild")
LOG = os.path.join(PROJ, "build_jpeg_log.txt")

PYROOT = r"C:\Users\ILLENIUM\.workbuddy\binaries\python\versions\3.13.12"
PYINC = os.path.join(PYROOT, "include")
PYLIBS = os.path.join(PYROOT, "libs")

OUT_NAME = "hstego_jpeg_toolbox_extension.so"
OUT_PATH = os.path.join(SRC, OUT_NAME)

VSDIR = r"C:\Program Files\Microsoft Visual Studio\18\Community"
KITS = r"C:\Program Files (x86)\Windows Kits\10"

# libjpeg 库本体需要的 46 个源文件（排除 cjpeg/djpeg/jpegtran/rd*/wr*/jmemansi 等工具与备用内存管理器）
LIBJPEG_C = [
    "jcapimin.c", "jcapistd.c", "jcarith.c", "jccoefct.c", "jccolor.c", "jcdctmgr.c",
    "jchuff.c", "jcinit.c", "jcmainct.c", "jcmarker.c", "jcmaster.c", "jcomapi.c",
    "jcparam.c", "jcprepct.c", "jcsample.c", "jctrans.c",
    "jdapimin.c", "jdapistd.c", "jdarith.c", "jdatadst.c", "jdatasrc.c", "jdcoefct.c",
    "jdcolor.c", "jddctmgr.c", "jdhuff.c", "jdinput.c", "jdmainct.c", "jdmarker.c",
    "jdmaster.c", "jdmerge.c", "jdpostct.c", "jdsample.c", "jdtrans.c",
    "jerror.c", "jfdctflt.c", "jfdctfst.c", "jfdctint.c",
    "jidctflt.c", "jidctfst.c", "jidctint.c",
    "jmemmgr.c", "jmemnobs.c", "jquant1.c", "jquant2.c", "jutils.c", "jaricom.c",
]

log = []


def p(s=""):
    log.append(str(s))
    print(s, flush=True)


def find_toolchain():
    msvc_roots = [d for d in glob.glob(os.path.join(VSDIR, "VC", "Tools", "MSVC", "*"))
                  if os.path.isdir(os.path.join(d, "include"))]
    msvc = sorted(msvc_roots)[-1] if msvc_roots else None

    cl = None
    if msvc:
        for cand in ("Hostx64\\x64", "Hostx64\\x86", "Hostx86\\x64"):
            cx = os.path.join(msvc, "bin", cand, "cl.exe")
            if os.path.exists(cx):
                cl = cx
                break

    sdk = None
    inc_root = os.path.join(KITS, "Include")
    if os.path.isdir(inc_root):
        for v in sorted(os.listdir(inc_root), reverse=True):
            if os.path.isdir(os.path.join(inc_root, v, "ucrt")):
                sdk = v
                break
    return msvc, cl, sdk


def main():
    p("=" * 72)
    p("hstego JPEG Toolbox 扩展构建（重编 libjpeg 路线）")
    p("=" * 72)

    for label, path in [("hstego-src", SRC), ("libjpeg 源码", JPEG_SRC),
                        ("libjpeg 头文件", JPEG_INC), ("Python include", PYINC),
                        ("Python libs(python313.lib)", PYLIBS)]:
        p("%-28s %s  [%s]" % (label, path, "OK" if os.path.isdir(path) else "缺失!"))

    missing = [f for f in LIBJPEG_C if not os.path.exists(os.path.join(JPEG_SRC, f))]
    if missing:
        p("FATAL: libjpeg 源文件缺失: %s" % missing)
        return 1
    p("libjpeg 源文件: %d/%d 齐备" % (len(LIBJPEG_C), len(LIBJPEG_C)))

    msvc, cl, sdk = find_toolchain()
    p("\nMSVC : %s" % msvc)
    p("cl   : %s" % cl)
    p("SDK  : %s" % sdk)
    if not cl or not sdk:
        p("FATAL: 找不到工具链")
        return 1

    # ---- 准备构建目录：放一份 jconfig.h ----
    os.makedirs(BUILD, exist_ok=True)
    jconfig_dst = os.path.join(BUILD, "jconfig.h")
    jconfig_src = os.path.join(JPEG_INC, "jconfig.h")
    with open(jconfig_src, "rb") as f:
        data = f.read()
    with open(jconfig_dst, "wb") as f:
        f.write(data)
    p("jconfig.h -> %s (%d 字节)" % (jconfig_dst, len(data)))

    # ---- 环境变量 ----
    sdk_inc = os.path.join(KITS, "Include", sdk)
    sdk_lib = os.path.join(KITS, "Lib", sdk)
    env = dict(os.environ)
    env["INCLUDE"] = ";".join([
        os.path.join(msvc, "include"),
        os.path.join(sdk_inc, "ucrt"),
        os.path.join(sdk_inc, "um"),
        os.path.join(sdk_inc, "shared"),
        os.path.join(sdk_inc, "winrt"),
        PYINC,
    ])
    env["LIB"] = ";".join([
        os.path.join(msvc, "lib", "x64"),
        os.path.join(sdk_lib, "ucrt", "x64"),
        os.path.join(sdk_lib, "um", "x64"),
        PYLIBS,
    ])
    env["PATH"] = os.path.dirname(cl) + os.pathsep + env.get("PATH", "")
    env["TMP"] = env.get("TMP") or os.environ.get("TEMP", r"C:\Windows\Temp")

    sources = [os.path.join(SRC, "src", "jpeg_toolbox_extension.c")]
    sources += [os.path.join(JPEG_SRC, f) for f in LIBJPEG_C]

    cmd = [cl, "/nologo", "/LD", "/O2", "/MD", "/W1",
           "/I", JPEG_SRC, "/I", JPEG_INC, "/I", BUILD, "/I", PYINC,
           "/D", "_CRT_SECURE_NO_WARNINGS",
           ] + sources + [
        "/link",
        "/OUT:" + OUT_PATH,
        "/FORCE:MULTIPLE" if False else "/INCREMENTAL:NO",
        "python313.lib",
    ]

    p("\n--- 编译（%d 个源文件，单次 cl 调用）---" % len(sources))
    p("cwd: %s" % BUILD)
    t0 = time.time()
    r = subprocess.run(cmd, cwd=BUILD, env=env, capture_output=True, text=True, errors="replace")
    dt = time.time() - t0

    out = (r.stdout or "") + (r.stderr or "")
    # 只把 error 与最后的汇总行留在日志里，warning 噪音太多
    errs = [ln for ln in out.splitlines() if (" error " in ln or "fatal error" in ln or ln.startswith("LINK :"))]
    p("exit=%d  用时 %.1fs" % (r.returncode, dt))
    if errs:
        p("--- 错误/链接信息 ---")
        for ln in errs[:40]:
            p("  " + ln)
    else:
        p("（无 error / LINK 信息）")

    ok = r.returncode == 0 and os.path.exists(OUT_PATH)
    if ok:
        size = os.path.getsize(OUT_PATH)
        p("\n[OK] 产出: %s  (%.2f MB)" % (OUT_PATH, size / 1048576.0))
    else:
        p("\n[FAIL] 未产出 %s" % OUT_PATH)
        p("完整输出见 %s" % LOG)

    # 完整输出存一份，方便排查
    with io.open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
        f.write("\n\n========== 编译器完整输出 ==========\n")
        f.write(out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
