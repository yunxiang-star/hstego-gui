# -*- coding: utf-8 -*-
"""
决定性实验 3: 头部失败是"确定性"还是"概率性"?
- 嵌入后立刻读头部 (不走 extract 的 try/except), 看真实报错
- 同一载体重复 3 次 (头部 nonce 每次随机 -> 头部比特每次不同)
- 抓 stc_hide 返回码
"""
import os, sys, io, random, time, contextlib, traceback
import numpy as np
from PIL import Image

ROOT = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48"
sys.path.insert(0, os.path.join(ROOT, "hstego-src"))
import hstegolib
from hstegolib import (jpeg_load, jpg_capacity, derive_password_seed,
                       decrypt_header, HEADER_SIZE, HEADER_COVER_LEN, Stego)

WORK = os.path.join(ROOT, "diag")
os.makedirs(WORK, exist_ok=True)
PWD = "baseline-pwd-2026"


class StcSpy:
    def __init__(self, real):
        self._real, self.log = real, []

    def __getattr__(self, name):
        fn = getattr(self._real, name)

        def w(*a):
            r = fn(*a)
            if name == "stc_hide":
                self.log.append(("hide", a[0], a[3], r))
            elif name == "stc_unhide":
                self.log.append(("unhide", a[0], a[2], r))
            return r
        return w


spy = StcSpy(hstegolib.stc)
hstegolib.stc = spy


def rand_bytes(n, seed=1234):
    return np.random.default_rng(seed).integers(0, 256, n, dtype=np.uint8).tobytes()


def probe(name, src_tiff, n=128, repeats=1, quality=90):
    cover = os.path.join(WORK, f"p2_{name}_cover.jpg")
    Image.open(src_tiff).convert("RGB").save(cover, "JPEG", quality=quality, subsampling=0)
    jpg0 = jpeg_load(cover)
    cap = jpg_capacity(jpg0)
    sec = os.path.join(WORK, f"p2_{name}_secret.bin")
    open(sec, "wb").write(rand_bytes(n))

    print(f"\n{'='*78}\n[{name}] q={quality} 容量={cap}B 载荷={n}B\n{'='*78}")
    if cap < n + 80:
        print("  容量不足, 跳过")
        return

    j = hstegolib.J_UNIWARD()
    for rep in range(repeats):
        stego = os.path.join(WORK, f"p2_{name}_stego_{rep}.jpg")
        spy.log.clear()
        buf = io.StringIO()
        t0 = time.perf_counter()
        try:
            with contextlib.redirect_stdout(buf):
                j.embed(cover, sec, PWD, stego)
        except Exception as e:
            print(f"  [rep{rep}] 嵌入异常 {type(e).__name__}: {e}")
            continue
        t_emb = time.perf_counter() - t0

        # 直接读头部 (不经过 extract 的 except)
        seed = derive_password_seed(PWD)
        so = Stego()
        try:
            hdr_bytes = so.unhide_header(jpeg_load(stego)["coef_arrays"][0], seed)
            plen = decrypt_header(PWD, hdr_bytes)
            hdr_ok = f"OK payload_len={plen}"
        except Exception as e:
            hdr_ok = f"失败 {type(e).__name__}: {e}"

        # 走官方 extract
        out = os.path.join(WORK, f"p2_{name}_out_{rep}.bin")
        buf2 = io.StringIO()
        t1 = time.perf_counter()
        with contextlib.redirect_stdout(buf2):
            j.extract(stego, PWD, out)
        t_ext = time.perf_counter() - t1
        got = open(out, "rb").read() if os.path.exists(out) else b""
        want = open(sec, "rb").read()

        hdr_log = [x for x in spy.log if x[0] == "hide" and x[1] == HEADER_COVER_LEN]
        print(f"  [rep{rep}] 嵌入 {t_emb:.1f}s  头部读取: {hdr_ok}")
        print(f"          提取 {t_ext:.1f}s  往返 {'✅ OK' if got == want else '❌ FAIL'}  "
              f"({len(got)}B/{len(want)}B)")
        print(f"          stc_hide 返回码: {[x[3] for x in hdr_log]}  "
              f"(头部那次 n=512,m=256)")
        if buf2.getvalue().strip():
            print(f"          extract stdout: {buf2.getvalue().strip()!r}")


T = os.path.join(ROOT, "testset")
probe("sailboat", os.path.join(T, "4.2.06_sailboat.tiff"), n=128, repeats=3)
probe("splash", os.path.join(T, "4.2.01_splash.tiff"), n=128, repeats=1)
probe("peppers", os.path.join(T, "4.2.07_peppers.tiff"), n=128, repeats=1)
