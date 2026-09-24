#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HStego 工程自测：验证「嵌入 → 提取」往返在空间域与 JPEG 域都正确。

用法：
    python selftest.py                  跑全部
    python selftest.py --only spatial   只跑空间域（PNG）
    python selftest.py --only jpeg      只跑 JPEG 域

这个脚本存在的意义：换机器 / 重装环境 / 改了 hstegolib 之后，
一条命令就能确认整条链路没坏。它只依赖工程内的 .venv，不碰任何外部服务。
"""
import argparse
import os
import sys
import traceback

# Windows 控制台默认是 GBK，中文会乱码，这里强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

import numpy as np
import imageio.v2 as imageio

PASSWORD = "MyP4ssw0rd101"
WORK = os.path.join(HERE, "output", "selftest")

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"  [{flag}] {name}" + (f"  —— {detail}" if detail else ""))


def make_fixtures():
    """生成一张确定性的测试图（不依赖任何外部图片）。"""
    os.makedirs(WORK, exist_ok=True)
    rng = np.random.default_rng(42)
    h = w = 512
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.sin(xx / 37.0) * 60 + np.cos(yy / 23.0) * 60 + 128
    img = np.stack([base, base * 0.9 + 20, base * 0.8 + 40], axis=-1)
    img += rng.normal(0, 6, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)

    png = os.path.join(WORK, "cover.png")
    jpg = os.path.join(WORK, "cover.jpg")
    txt = os.path.join(WORK, "secret.txt")
    imageio.imwrite(png, img)
    imageio.imwrite(jpg, img, quality=90)
    with open(txt, "w", encoding="utf-8") as f:
        f.write("隐写往返测试：UNIWARD 定代价 + STC 最小失真编码。" * 3)
    return png, jpg, txt


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def test_spatial(hstegolib, cover, secret):
    print("\n[空间域 S-UNIWARD / PNG]")
    stego = os.path.join(WORK, "stego.png")
    out = os.path.join(WORK, "out_spatial.txt")
    s = hstegolib.S_UNIWARD()

    cap = hstegolib.spatial_capacity(imageio.imread(cover))
    record("容量查询", cap > 0, f"{cap} 字节")

    s.embed(cover, secret, PASSWORD, stego)
    record("嵌入成功", os.path.exists(stego),
           f"{os.path.getsize(cover)} B → {os.path.getsize(stego)} B")

    s.extract(stego, PASSWORD, out)
    ok = read_bytes(out) == read_bytes(secret)
    record("提取内容与原文一致", ok)

    a = imageio.imread(cover).astype(int)
    b = imageio.imread(stego).astype(int)
    changed = int((a != b).sum())
    pct = 100.0 * changed / a.size
    record("确认像素被真正改写（非复制）", 0 < changed,
           f"改动 {changed}/{a.size} 个通道值 = {pct:.3f}%")

    bad = os.path.join(WORK, "out_bad.txt")
    try:
        s.extract(stego, "WrongPassword", bad)
        leaked = read_bytes(bad) == read_bytes(secret)
        record("错误口令无法还原原文", not leaked)
    except Exception as e:
        record("错误口令无法还原原文", True, f"直接抛错 {type(e).__name__}")


def test_jpeg(hstegolib, cover, secret):
    print("\n[JPEG 域 J-UNIWARD / JPEG]")
    stego = os.path.join(WORK, "stego.jpg")
    out = os.path.join(WORK, "out_jpeg.txt")
    j = hstegolib.J_UNIWARD()

    cap = hstegolib.jpg_capacity(hstegolib.jpeg_load(cover))
    record("容量查询", cap > 0, f"{cap} 字节")

    j.embed(cover, secret, PASSWORD, stego)
    record("嵌入成功", os.path.exists(stego),
           f"{os.path.getsize(cover)} B → {os.path.getsize(stego)} B")

    j.extract(stego, PASSWORD, out)
    ok = read_bytes(out) == read_bytes(secret)
    record("提取内容与原文一致", ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["spatial", "jpeg"], default=None)
    args = ap.parse_args()

    print("=" * 62)
    print(" HStego 工程自测")
    print("=" * 62)

    print("\n[环境]")
    print(f"  解释器: {sys.executable}")
    print(f"  工作目录: {HERE}")

    import hstegolib
    print(f"  已加载 hstegolib: {os.path.basename(hstegolib.__file__)}")

    cover_png, cover_jpg, secret = make_fixtures()
    print(f"  测试素材已就绪: {WORK}")

    try:
        if args.only in (None, "spatial"):
            test_spatial(hstegolib, cover_png, secret)
        if args.only in (None, "jpeg"):
            test_jpeg(hstegolib, cover_jpg, secret)
    except Exception:
        print("\n!! 测试过程中抛出异常：")
        traceback.print_exc()
        record("整体执行", False, "见上方堆栈")

    print("\n" + "=" * 62)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f" 结果: {passed}/{total} 项通过")
    for name, ok, detail in results:
        if not ok:
            print(f"   ✗ {name}  {detail}")
    print("=" * 62)

    return 0 if passed == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
