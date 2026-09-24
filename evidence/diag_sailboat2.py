# -*- coding: utf-8 -*-
"""
J-UNIWARD 往返失败 —— 根因定位 (决定性实验)
=============================================
假设: 嵌入按【载体】的通道容量切分消息; 提取按【载密图】的通道容量重新切分。
      只要嵌入让非零系数个数变化, 两侧切分就错位 -> 密文拼错 -> AES 校验失败 -> 空文件。

证法: 手工重现提取流程, 两套容量各跑一次, 比较解出的密文长度与校验结果。
"""
import os, sys, io, time, zlib, hashlib, contextlib, traceback
import numpy as np
from PIL import Image

ROOT = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48"
sys.path.insert(0, os.path.join(ROOT, "hstego-src"))
import hstegolib
from hstegolib import (Cipher, Stego, jpeg_load, jpeg_save, jpg_channel_capacity,
                       effective_payload_capacities, split_lengths_by_capacity,
                       derive_password_seed, decrypt_header, HEADER_SIZE,
                       HEADER_COVER_LEN)

WORK = os.path.join(ROOT, "diag")
os.makedirs(WORK, exist_ok=True)
PWD = "baseline-pwd-2026"
TIFF = os.path.join(ROOT, "testset", "4.2.06_sailboat.tiff")
COVER = os.path.join(WORK, "sb_cover.jpg")
STEGO = os.path.join(WORK, "sb_stego.jpg")


def rand_bytes(n, seed=1234):
    """不可压缩载荷 (真随机), 才是现实最坏情况"""
    return np.random.default_rng(seed).integers(0, 256, n, dtype=np.uint8).tobytes()


def caps_of(jpg, nch=3):
    return effective_payload_capacities(
        [jpg_channel_capacity(jpg["coef_arrays"][c]) for c in range(nch)])


Image.open(TIFF).convert("RGB").save(COVER, "JPEG", quality=90, subsampling=0)
jpg_cover = jpeg_load(COVER)
cap_cover = caps_of(jpg_cover)
print(f"载体: {os.path.basename(COVER)}  {os.path.getsize(COVER)} B")
print(f"载体通道有效容量: {cap_cover}  合计 {sum(cap_cover)}")

N = 128
data = rand_bytes(N)
sec = os.path.join(WORK, "sb_secret.bin")
open(sec, "wb").write(data)
ct_len = len(Cipher(PWD).encrypt(sec))
print(f"载荷 {N}B (真随机) -> 密文 {ct_len}B   容得下? {ct_len <= sum(cap_cover)}")
print(f"  zlib.compress({N}) = {len(zlib.compress(data,9))}  -> 60+该值 = {60+len(zlib.compress(data,9))}")

# ---------------------------------------------------------------- 真实调用
print("\n" + "=" * 78)
print("一、走官方 API 的往返")
print("=" * 78)
j = hstegolib.J_UNIWARD()
buf = io.StringIO()
t0 = time.perf_counter()
try:
    with contextlib.redirect_stdout(buf):
        j.embed(COVER, sec, PWD, STEGO)
    print(f"  嵌入成功  {time.perf_counter()-t0:.2f}s  "
          f"stego 存在={os.path.exists(STEGO)}  {os.path.getsize(STEGO) if os.path.exists(STEGO) else 0}B")
except Exception as e:
    print(f"  嵌入失败: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)

out = os.path.join(WORK, "sb_out.bin")
buf2 = io.StringIO()
t1 = time.perf_counter()
with contextlib.redirect_stdout(buf2):
    j.extract(STEGO, PWD, out)
dt = time.perf_counter() - t1
got = open(out, "rb").read() if os.path.exists(out) else b""
print(f"  提取耗时 {dt:.2f}s   取出 {len(got)}B / 期望 {N}B")
print(f"  往返: {'OK ✅' if got == data else 'FAIL ❌'}")
print(f"  extract 的 stdout: {buf2.getvalue().strip()!r}")

# ---------------------------------------------------------------- 系数/容量漂移
print("\n" + "=" * 78)
print("二、非零系数与容量是否漂移")
print("=" * 78)
jpg_stego = jpeg_load(STEGO)
cap_stego = caps_of(jpg_stego)
nz_c = [int(np.count_nonzero(jpg_cover["coef_arrays"][c])) for c in range(3)]
nz_s = [int(np.count_nonzero(jpg_stego["coef_arrays"][c])) for c in range(3)]
print(f"  每通道非零系数  载体 {nz_c}  ->  载密 {nz_s}")
print(f"  非零数变化      {[s-c for c,s in zip(nz_c,nz_s)]}")
print(f"  每通道有效容量  载体 {cap_cover}  ->  载密 {cap_stego}")
print(f"  容量变化        {[s-c for c,s in zip(cap_cover,cap_stego)]}")

# ---------------------------------------------------------------- 决定性实验
print("\n" + "=" * 78)
print("三、决定性实验: 两套容量各切分一次, 看哪套能解出")
print("=" * 78)
payload_len = len(Cipher(PWD).encrypt(sec))   # 199
print(f"  (头里存的是 payload_len, 提取时靠它还原 —— 先验证头能读出来)")
seed = derive_password_seed(PWD)
stego_obj = Stego()
try:
    hdr = stego_obj.unhide_header(jpg_stego["coef_arrays"][0], seed)
    plen_read = decrypt_header(PWD, hdr)
    print(f"  头部读取成功: payload_len = {plen_read} (期望 {payload_len})  "
          f"{'一致' if plen_read == payload_len else '不一致!'}")
except Exception as e:
    print(f"  头部读取失败: {type(e).__name__}: {e}")
    plen_read = payload_len


def try_decode(caps, tag):
    lengths = split_lengths_by_capacity(plen_read, caps)
    ct = bytearray()
    for c in range(3):
        if c == 0:
            ct += stego_obj.unhide_raw(jpg_stego["coef_arrays"][c], seed,
                                       lengths[c], reserved_prefix=HEADER_COVER_LEN)
        else:
            ct += stego_obj.unhide_raw(jpg_stego["coef_arrays"][c], seed, lengths[c])
    plain = Cipher(PWD).decrypt(bytes(ct))
    ok = bytes(plain) == data
    print(f"  [{tag}] 切分={lengths} (和={sum(lengths)})  密文取回 {len(ct)}B  "
          f"-> {'解出 OK ✅' if ok else 'FAIL ❌ (' + str(len(plain)) + 'B)'}")
    return ok


print(f"  期望切分长度: {split_lengths_by_capacity(plen_read, cap_cover)}  (embed 用的)")
a = try_decode(cap_cover, "用载体容量切分")
b = try_decode(cap_stego, "用载密图容量切分 (官方 extract 的做法)")
print("\n  >>> 结论:", "切分错位就是根因 ✅" if (a and not b) else
      ("两套都能解, 另有原因" if (a and b) else "两套都解不出, 需另找原因"))
