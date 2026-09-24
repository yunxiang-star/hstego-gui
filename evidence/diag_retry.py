# -*- coding: utf-8 -*-
"""sailboat 失败能否被"换编码参数"绕过? —— 决定 GUI 的重试策略"""
import os, sys, io, time, contextlib
import numpy as np
from PIL import Image

ROOT = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48"
sys.path.insert(0, os.path.join(ROOT, "hstego-src"))
import hstegolib
from hstegolib import jpeg_load, jpg_capacity, derive_password_seed, decrypt_header, Stego

WORK = os.path.join(ROOT, "diag")
PWD = "baseline-pwd-2026"
TIFF = os.path.join(ROOT, "testset", "4.2.06_sailboat.tiff")
img = Image.open(TIFF).convert("RGB")

CASES = [
    ("q90/4:4:4 (原设置)", 90, 0, 128),
    ("q90/4:2:0 (默认子采样)", 90, 2, 128),
    ("q85/4:4:4", 85, 0, 128),
    ("q95/4:4:4", 95, 0, 128),
    ("q80/4:4:4", 80, 0, 128),
    ("q90/4:4:4 小载荷32B", 90, 0, 32),
]

print(f"{'方案':<26}{'容量':>7}{'载荷':>6}  头部   往返   耗时")
print("-" * 78)
for tag, q, ss, n in CASES:
    cpath = os.path.join(WORK, f"rt_q{q}_s{ss}.jpg")
    img.save(cpath, "JPEG", quality=q, subsampling=ss)
    cap = jpg_capacity(jpeg_load(cpath))
    data = np.random.default_rng(1234).integers(0, 256, n, dtype=np.uint8).tobytes()
    sec = os.path.join(WORK, f"rt_sec_{q}_{ss}_{n}.bin")
    open(sec, "wb").write(data)
    stego = os.path.join(WORK, f"rt_stego_{q}_{ss}_{n}.jpg")
    out = os.path.join(WORK, f"rt_out_{q}_{ss}_{n}.bin")

    if cap < n + 80:
        print(f"{tag:<26}{cap:>7}{n:>6}  容量不足, 跳过")
        continue

    j = hstegolib.J_UNIWARD()
    buf = io.StringIO()
    t0 = time.perf_counter()
    try:
        with contextlib.redirect_stdout(buf):
            j.embed(cpath, sec, PWD, stego)
    except Exception as e:
        print(f"{tag:<26}{cap:>7}{n:>6}  嵌入异常 {type(e).__name__}: {str(e)[:30]}")
        continue

    # 头部直读
    try:
        hdr = Stego().unhide_header(jpeg_load(stego)["coef_arrays"][0], derive_password_seed(PWD))
        decrypt_header(PWD, hdr)
        h = "OK "
    except Exception:
        h = "坏 "

    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        j.extract(stego, PWD, out)
    got = open(out, "rb").read() if os.path.exists(out) else b""
    dt = time.perf_counter() - t0
    print(f"{tag:<26}{cap:>7}{n:>6}  {h}  {'✅ OK' if got == data else '❌ FAIL':<7} {dt:.1f}s")

print()
print("注: 官方 API 若头部损坏 -> extract() 静默写 0 字节, 不抛异常。")
print("    GUI 必须靠「输出为空」判定失败, 而不是 try/except。")
