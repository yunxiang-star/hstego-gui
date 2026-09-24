#!/usr/bin/env python3
"""cover / stego 对比工具。

计算不可感知性指标，并生成一张「封面 | 隐写图 | 放大差异」的对比图。

用法:
    python compare.py <cover image> <stego image> [--out 输出目录] [--gain 20]

指标说明（隐写领域标准做法）:
    PSNR  峰值信噪比，越大越不可见。> 40 dB 通常认为视觉不可察觉。
    MSE   均方误差。
    MaxAE 单像素最大绝对误差（逐通道）。
    SSIM  结构相似度，1.0 表示结构完全一致（需 scikit-image，可选）。

注意: 本工具只读，不会修改任何输入文件。
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

DEFAULT_OUT = "output/compare"


def load_pair(cover_path, stego_path):
    """读入两张图，对齐尺寸与通道数。"""
    a = Image.open(cover_path)
    b = Image.open(stego_path)
    if a.size != b.size:
        raise SystemExit(
            f"尺寸不一致: cover {a.size} vs stego {b.size}\n"
            "隐写前后图像尺寸必须完全相同。"
        )
    a = a.convert("RGB")
    b = b.convert("RGB")
    return a, b


def metrics(cover_arr, stego_arr):
    """逐通道计算 MSE / PSNR / MaxAE。"""
    c = cover_arr.astype(np.float64)
    s = stego_arr.astype(np.float64)
    diff = c - s
    mse = float(np.mean(diff ** 2))
    max_ae = int(np.max(np.abs(diff))) if diff.size else 0
    if mse == 0:
        psnr = float("inf")
    else:
        psnr = float(10.0 * np.log10((255.0 ** 2) / mse))
    return mse, psnr, max_ae, diff


def build_comparison(cover_img, stego_img, diff, gain, out_path):
    """拼一张三栏对比图：封面 / 隐写图 / 放大后的差异热图。"""
    w, h = cover_img.size

    # 差异图：绝对误差 × gain，裁到 0..255
    amp = np.clip(np.abs(diff) * gain, 0, 255).astype(np.uint8)
    diff_img = Image.fromarray(amp)

    # 若原图很小，等比放大方便肉眼看
    scale = 1
    while max(w, h) * scale < 480:
        scale += 1
    if scale > 1:
        cover_img = cover_img.resize((w * scale, h * scale), Image.NEAREST)
        stego_img = stego_img.resize((w * scale, h * scale), Image.NEAREST)
        diff_img = diff_img.resize((w * scale, h * scale), Image.NEAREST)

    cw, ch = cover_img.size
    pad, bar = 12, 34
    canvas = Image.new("RGB", (cw * 3 + pad * 4, ch + pad * 2 + bar), (255, 255, 255))
    canvas.paste(cover_img, (pad, bar + pad))
    canvas.paste(stego_img, (pad * 2 + cw, bar + pad))
    canvas.paste(diff_img, (pad * 3 + cw * 2, bar + pad))

    draw = ImageDraw.Draw(canvas)
    labels = ["Cover (original)", "Stego (after embedding)", f"|Difference| x{gain}"]
    for i, text in enumerate(labels):
        draw.text((pad + i * (cw + pad), 10), text, fill=(0, 0, 0))

    canvas.save(out_path)
    return canvas.size


def main():
    ap = argparse.ArgumentParser(description="Compare a cover image with its stego version.")
    ap.add_argument("cover", help="original cover image")
    ap.add_argument("stego", help="stego image produced by hstego")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"output directory (default: {DEFAULT_OUT})")
    ap.add_argument("--gain", type=int, default=20, help="amplification factor for the diff panel (default: 20)")
    args = ap.parse_args()

    for p in (args.cover, args.stego):
        if not os.path.isfile(p):
            sys.exit(f"文件不存在: {p}")

    cover_img, stego_img = load_pair(args.cover, args.stego)
    cover_arr = np.asarray(cover_img)
    stego_arr = np.asarray(stego_img)

    mse, psnr, max_ae, diff = metrics(cover_arr, stego_arr)

    # 有效载荷（消息长度）不在这里猜，只报像素层面的失真
    changed = int(np.count_nonzero(np.any(diff != 0, axis=2)))
    total = cover_arr.shape[0] * cover_arr.shape[1]
    rate = 100.0 * changed / total if total else 0.0

    print(f"Cover : {args.cover}")
    print(f"Stego : {args.stego}")
    print(f"Size  : {cover_img.size[0]} x {cover_img.size[1]} px")
    print("")
    print(f"  MSE           : {mse:.4f}")
    print(f"  PSNR          : {psnr:.2f} dB" + ("  (bit-identical)" if psnr == float('inf') else ""))
    print(f"  Max abs error : {max_ae} / 255")
    print(f"  Pixels changed: {changed} / {total}  ({rate:.2f}%)")
    if psnr != float("inf"):
        if psnr >= 40:
            print("  Verdict       : visually imperceptible (PSNR >= 40 dB)")
        elif psnr >= 35:
            print("  Verdict       : likely imperceptible, inspect carefully")
        else:
            print("  Verdict       : distortion may be visible")

    os.makedirs(args.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.stego))[0]
    out_path = os.path.join(args.out, f"{base}-comparison.png")
    size = build_comparison(cover_img, stego_img, diff, args.gain, out_path)
    print("")
    print(f"Comparison image written: {out_path}  ({size[0]}x{size[1]})")


if __name__ == "__main__":
    main()
