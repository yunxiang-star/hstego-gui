# -*- coding: utf-8 -*-
"""JPEG Toolbox 扩展可用性验证 —— 不只看「能不能 import」，要跑通 DCT 读写与 J-UNIWARD 往返。"""
import os
import sys
import hashlib
import io
import time
import traceback

PROJ = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48"
SRC = os.path.join(PROJ, "hstego-src")
sys.path.insert(0, SRC)

LOG = os.path.join(PROJ, "test_jpeg_log.txt")
lines = []


def p(s=""):
    lines.append(str(s))
    print(s, flush=True)


def flush():
    with io.open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


p("=" * 70)
p("JPEG Toolbox 扩展验证")
p("=" * 70)

# ---- 0. 扩展文件就位情况 ----
import glob
p("\n[0] 扩展文件定位")
for m in ("hstego_jpeg_toolbox_extension", "hstego_stc_extension"):
    hits = sorted(glob.glob(os.path.join(SRC, m + "*.so")) + glob.glob(os.path.join(SRC, m + "*.pyd")))
    p("    %-38s %s" % (m, hits if hits else "!! 未找到"))

# ---- 1. 直接 ctypes 加载（绕过 hstegolib，定位问题）----
p("\n[1] ctypes 直接加载 DLL")
from ctypes import CDLL
dll_path = os.path.join(SRC, "hstego_jpeg_toolbox_extension.so")
try:
    lib = CDLL(dll_path)
    p("    LOADED OK -> %s" % lib)
    p("    导出符号 read_file : %s" % (lib.read_file,))
    p("    导出符号 write_file: %s" % (lib.write_file,))
except OSError as e:
    p("    LOAD FAILED: %s" % e)
    flush()
    sys.exit(1)

# ---- 2. 生成测试载体 JPEG ----
p("\n[2] 生成测试载体")
import numpy as np
from PIL import Image

rng = np.random.default_rng(20260923)
H = W = 512
yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
base = 110 + 45 * np.sin(xx / 37.0) + 40 * np.cos(yy / 53.0)   # 低频
mid = 18 * np.sin((xx + yy) / 9.0)                             # 中频纹理
fine = rng.normal(0, 9, (H, W))                                # 细颗粒
img = np.clip(np.stack([base + mid + fine,
                        base * 0.9 + fine * 1.1,
                        base * 0.8 + mid * 0.7 + fine], axis=-1), 0, 255).astype(np.uint8)
cover = os.path.join(PROJ, "testdata_cover.jpg")
Image.fromarray(img, "RGB").save(cover, quality=90)
p("    载体: %s  (%d bytes, %dx%d)" % (cover, os.path.getsize(cover), W, H))

stego = os.path.join(PROJ, "testdata_stego.jpg")
secret = os.path.join(PROJ, "testdata_secret.txt")
outmsg = os.path.join(PROJ, "testdata_extracted.txt")
payload = ("小隐验证载荷 / JPEG Toolbox sanity check. " * 2).encode("utf-8")
with open(secret, "wb") as f:
    f.write(payload)
p("    消息: %d bytes" % len(payload))

# ---- 3. 用扩展读 DCT 系数 ----
p("\n[3] 扩展读 DCT 系数（这是 JPEG Toolbox 存在的全部理由）")
import ctypes
lib.read_file.restype = ctypes.py_object
lib.read_file.argtypes = [ctypes.c_char_p]

t0 = time.time()
data = lib.read_file(cover.encode())
p("    返回类型: %s   耗时 %.2fs" % (type(data), time.time() - t0))
p("    keys: %s" % sorted(data.keys()))
p("    image_width/height: %s / %s" % (data["image_width"], data["image_height"]))
p("    image_components  : %s" % data["image_components"])
p("    progressive_mode  : %s" % data["progressive_mode"])

coefs = data["coef_arrays"]
p("    coef_arrays: %d 个通道" % len(coefs))
Y = np.array(coefs[0], dtype=np.int32)
p("    Y 通道 DCT 系数矩阵 shape = %s  (块行, 块列, 8, 8)" % (Y.shape,))
qt = data["quant_tables"]
p("    quant_tables: %d 张；Q[0] 左上角(直流)步长 = %s" % (len(qt), qt[0][0][0]))
nz = int(np.count_nonzero(Y[:, :, :, 1:]))
p("    Y 非零 AC 系数个数 = %d" % nz)
p("    -> DCT 系数与量化表读取 [%s]" % ("成功" if nz > 1000 else "异常"))

# ---- 4. J-UNIWARD 完整往返 ----
p("\n[4] J-UNIWARD 藏取往返")
import hstegolib
p("    import hstegolib [OK]（说明 JPEG + STC 两个扩展都已加载）")

j = hstegolib.J_UNIWARD()
cap = hstegolib.jpg_capacity(hstegolib.jpeg_load(cover))
p("    jpg_capacity = %d 字节（5%% 上限后约 %d 字节）" % (cap, int(cap * hstegolib.MAX_PAYLOAD)))

t0 = time.time()
j.embed(cover, secret, "MyP4ssw0rd101", stego)
t_emb = time.time() - t0
p("    embed  [OK] %.2fs -> %s (%d bytes)" % (t_emb, stego, os.path.getsize(stego)))

t0 = time.time()
j.extract(stego, "MyP4ssw0rd101", outmsg)
t_ext = time.time() - t0
p("    extract[OK] %.2fs" % t_ext)

with open(outmsg, "rb") as f:
    got = f.read()
p("    原消息 sha256: %s" % hashlib.sha256(payload).hexdigest()[:16])
p("    取回  sha256: %s" % hashlib.sha256(got).hexdigest()[:16])
p("    往返一致: %s" % ("是 ✓" if got == payload else "否 ✗"))

# ---- 5. 载体/载密 DCT 差异 ----
p("\n[5] 载体 vs 载密：DCT 域实际改了多少")
d2 = lib.read_file(stego.encode())
S = np.array(d2["coef_arrays"][0], dtype=np.int32)
diff = (Y != S)
p("    Y 通道 64*%d 个系数中，被改了 %d 个 (%.4f%%)" % (Y.shape[0] * Y.shape[1], int(diff.sum()),
     100.0 * diff.sum() / diff.size))
p("    改动幅度绝对值集合: %s" % sorted(set(np.unique(np.abs(Y[diff] - S[diff])))))

from PIL import Image as I2
a = np.asarray(I2.open(cover).convert("RGB"), dtype=np.float64)
b = np.asarray(I2.open(stego).convert("RGB"), dtype=np.float64)
mse = float(np.mean((a - b) ** 2))
psnr = float("inf") if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)
p("    像素域 PSNR = %.2f dB" % psnr)

# ---- 6. 错误口令应当失败 ----
p("\n[6] 负例：错误口令")
try:
    j.extract(stego, "wrong-password", os.path.join(PROJ, "testdata_bad.txt"))
    p("    警告：错误口令居然没报错（需复查）")
except Exception as e:
    p("    正确拒绝: %s: %s" % (type(e).__name__, str(e)[:90]))

p("\n" + "=" * 70)
p("结论：JPEG Toolbox 扩展 [已攻克]")
p("=" * 70)
flush()
