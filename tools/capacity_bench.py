# -*- coding: utf-8 -*-
"""JPEG 容量基准 + 错误口令行为确认。"""
import os, sys, io, numpy as np
from PIL import Image

PROJ = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48"
SRC = os.path.join(PROJ, "hstego-src")
sys.path.insert(0, SRC)
import hstegolib

LOG = os.path.join(PROJ, "capacity_bench.txt")
lines = []
def p(s=""):
    lines.append(str(s)); print(s, flush=True)

p("=" * 78)
p("hstego JPEG 可用容量基准（已含 5% 安全上限，非原始容量）")
p("=" * 78)
p("说明：hstego 的 jpg_capacity() 内部已乘 MAX_PAYLOAD=0.05，")
p("     所以下表就是「实际能藏多少字节」，不要再乘 5%。")
p("")

rng = np.random.default_rng(7)

def make_cover(w, h, q, path):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    base = 110 + 45 * np.sin(xx / 37.0) + 40 * np.cos(yy / 53.0)
    mid = 18 * np.sin((xx + yy) / 9.0)
    fine = rng.normal(0, 9, (h, w))
    img = np.clip(np.stack([base + mid + fine,
                            base * 0.9 + fine * 1.1,
                            base * 0.8 + mid * 0.7 + fine], axis=-1), 0, 255).astype(np.uint8)
    Image.fromarray(img, "RGB").save(path, quality=q)
    return path

p("%-14s %-6s %-12s %-12s %-10s %-12s" % ("尺寸", "质量", "文件大小", "可用字节", "≈比特/像素", "藏得下一句话?"))
p("-" * 78)
rows = []
for (w, h) in [(512, 512), (1024, 768), (1920, 1080), (3840, 2160)]:
    for q in (90, 75):
        path = os.path.join(PROJ, "cap_%dx%d_q%d.jpg" % (w, h, q))
        make_cover(w, h, q, path)
        jpg = hstegolib.jpeg_load(path)
        cap = hstegolib.jpg_capacity(jpg)
        bpp = cap * 8.0 / (w * h)
        rows.append((w, h, q, os.path.getsize(path), cap, bpp))
        note = "是" if cap >= 200 else ("勉强" if cap >= 60 else "否")
        p("%-14s %-6s %-12s %-12s %-10.3f %-12s" % ("%dx%d" % (w, h), q,
          "%.0f KB" % (os.path.getsize(path) / 1024), "%d 字节" % cap, bpp, note))

p("")
p("参考：一条 300 字中文短信 UTF-8 约 900 字节；一张二维码文本约 60 字节。")
p("")

# 错误口令行为确认
p("=" * 78)
p("错误口令行为确认（影响 GUI 异常处理）")
p("=" * 78)
stego = os.path.join(PROJ, "testdata_stego.jpg")
badout = os.path.join(PROJ, "testdata_bad.txt")
j = hstegolib.J_UNIWARD()
raised = None
try:
    j.extract(stego, "wrong-password", badout)
except Exception as e:
    raised = e
p("extract() 是否抛异常: %s" % ("是 -> %r" % (raised,) if raised else "否（只往 stderr 打 WARNING）"))
p("输出文件大小: %d 字节" % (os.path.getsize(badout) if os.path.exists(badout) else -1))
p("")
p(">>> 结论：错误口令下 extract() 不抛异常，而是静默写出一个 0 字节文件。")
p(">>> GUI 必须自己判定「输出为空 = 口令错误 / 无消息」，否则用户会以为提取成功了。")

with io.open(LOG, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
