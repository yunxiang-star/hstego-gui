# -*- coding: utf-8 -*-
"""
hstego 评测基线 v2 (Day 6-8 验收物)
====================================
相对 v1 的三处修正:
  1. 载荷改为【真随机】(不可压缩) —— 原 v1 用的等差序列被 zlib 压掉 30 倍, 数据失真
  2. 载荷大小按【密文长度】精确配平 —— capacity 卡的是密文, 不是原始字节
     密文长度 = 60( salt16+nonce16+tag16+magic4+len8 ) + len(zlib.compress(data,9))
  3. 增加【嵌入后自检】列 —— J-UNIWARD 往返会确定性失败, 必须每次验证

输出: baseline_results.csv + baseline_report.md
"""
import os, sys, time, hashlib, io, zlib, traceback, contextlib
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

ROOT = r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48"
sys.path.insert(0, os.path.join(ROOT, "hstego-src"))
import hstegolib
import imageio.v2 as imageio

TESTSET = os.path.join(ROOT, "testset")
WORK = os.path.join(ROOT, "baseline")
OUTDIR = os.path.join(ROOT, "baseline")
os.makedirs(WORK, exist_ok=True)

PASSWORD = "baseline-pwd-2026"
TARGET_PAYLOAD = 128          # 目标载荷 (字节), 若容量不足则下调
JPEG_QUALITY = 90
CIPHER_FIXED = 60             # 密文固定开销


# ---------------------------------------------------------------- 指标
def psnr(a, b):
    a, b = a.astype(np.float64), b.astype(np.float64)
    mse = np.mean((a - b) ** 2)
    return float("inf") if mse == 0 else 10.0 * np.log10(255.0 ** 2 / mse)


def ssim(a, b):
    """Wang et al. 2004, 8-bit 灰度, 高斯窗 sigma=1.5"""
    a, b = a.astype(np.float64), b.astype(np.float64)
    L, K1, K2, S = 255.0, 0.01, 0.03, 1.5
    C1, C2 = (K1 * L) ** 2, (K2 * L) ** 2
    kw = dict(sigma=S, truncate=3.5, mode="reflect")
    ma, mb = gaussian_filter(a, **kw), gaussian_filter(b, **kw)
    maa, mbb, mab = ma * ma, mb * mb, ma * mb
    sa = gaussian_filter(a * a, **kw) - maa
    sb = gaussian_filter(b * b, **kw) - mbb
    sab = gaussian_filter(a * b, **kw) - mab
    return float(np.mean(((2 * mab + C1) * (2 * sab + C2)) /
                         ((maa + mbb + C1) * (sa + sb + C2))))


def to_gray(arr):
    if arr.ndim == 2:
        return arr
    return np.round(0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2])


def entropy(arr):
    g = to_gray(arr).astype(np.uint8).ravel()
    h = np.bincount(g, minlength=256).astype(np.float64)
    p = h / h.sum()
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def cipher_len(data):
    return CIPHER_FIXED + len(zlib.compress(data, 9))


def fit_payload(pool, capacity, lo=8):
    """在 capacity 内取最长的 pool 前缀"""
    for n in range(len(pool), lo - 1, -1):
        if cipher_len(pool[:n]) <= capacity:
            return n
    return 0


@contextlib.contextmanager
def quiet():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# ---------------------------------------------------------------- 单张
def run_one(name, src_tiff, results, pool):
    print(f"\n{'='*80}\n[{name}]  {os.path.basename(src_tiff)}\n{'='*80}", flush=True)
    try:
        with Image.open(src_tiff) as im:
            im.load()
            cover_pil = im.copy()
    except Exception as e:
        print(f"  跳过: 文件无法识别 ({type(e).__name__})", flush=True)
        results.append({"image": name, "domain": "-",
                        "status": f"文件损坏({type(e).__name__})"})
        return

    arr0 = np.array(cover_pil)
    print(f"  原始 {cover_pil.size[0]}x{cover_pil.size[1]} {cover_pil.mode}  "
          f"熵={entropy(arr0):.3f} bpp", flush=True)

    for domain in ("spatial", "jpeg"):
        rec = {"image": name, "domain": domain, "status": "OK"}
        try:
            if domain == "spatial":
                cover = os.path.join(WORK, f"{name}_cover.png")
                cover_pil.save(cover, "PNG")
                engine = hstegolib.S_UNIWARD()
                with quiet():
                    cap = hstegolib.spatial_capacity(imageio.imread(cover))
                stego = os.path.join(WORK, f"{name}_stego.png")
            else:
                cover = os.path.join(WORK, f"{name}_cover_q{JPEG_QUALITY}.jpg")
                (cover_pil.convert("L") if cover_pil.mode == "L"
                 else cover_pil.convert("RGB")).save(
                    cover, "JPEG", quality=JPEG_QUALITY, subsampling=0)
                engine = hstegolib.J_UNIWARD()
                with quiet():
                    cap = hstegolib.jpg_capacity(hstegolib.jpeg_load(cover))
                stego = os.path.join(WORK, f"{name}_stego_q{JPEG_QUALITY}.jpg")

            rec["capacity_bytes"] = cap
            rec["cover_bytes"] = os.path.getsize(cover)

            used = fit_payload(pool[:TARGET_PAYLOAD], cap)
            if used < 8:
                rec["status"] = f"容量不足({cap}B)"
                print(f"  [{domain:<7}] 跳过: {rec['status']}", flush=True)
                results.append(rec)
                continue

            payload = pool[:used]
            secret = os.path.join(WORK, f"{name}_{domain}_secret.bin")
            with open(secret, "wb") as f:
                f.write(payload)
            want = hashlib.sha256(payload).hexdigest()
            rec["payload_bytes"] = used
            rec["cipher_bytes"] = cipher_len(payload)
            rec["overhead"] = rec["cipher_bytes"] - used

            t0 = time.perf_counter()
            with quiet():
                engine.embed(cover, secret, PASSWORD, stego)
            rec["embed_s"] = time.perf_counter() - t0

            got_path = os.path.join(WORK, f"{name}_{domain}_extracted.bin")
            t1 = time.perf_counter()
            with quiet():
                engine.extract(stego, PASSWORD, got_path)
            rec["extract_s"] = time.perf_counter() - t1

            got = open(got_path, "rb").read() if os.path.exists(got_path) else b""
            rec["roundtrip"] = "OK" if hashlib.sha256(got).hexdigest() == want else "FAIL"
            rec["extract_size"] = len(got)

            a = np.array(Image.open(cover))
            b = np.array(Image.open(stego))
            if a.shape != b.shape:
                rec["status"] = f"形状不一致 {a.shape}/{b.shape}"
                results.append(rec)
                continue
            rec["psnr_db"] = psnr(a, b)
            rec["ssim"] = ssim(to_gray(a), to_gray(b))
            diff = np.abs(a.astype(np.int32) - b.astype(np.int32))
            rec["changed_pct"] = 100.0 * np.count_nonzero(diff) / diff.size
            rec["max_delta"] = int(diff.max())
            rec["stego_bytes"] = os.path.getsize(stego)

            print(f"  [{domain:<7}] 容量={cap:>6}B 载荷={used:>4}B(密文{rec['cipher_bytes']:>4}B) "
                  f"PSNR={rec['psnr_db']:>6.2f}dB SSIM={rec['ssim']:.6f} "
                  f"改={rec['changed_pct']:>5.2f}% 嵌={rec['embed_s']:>5.1f}s "
                  f"取={rec['extract_s']:>4.1f}s 往返={rec['roundtrip']}", flush=True)
        except Exception as e:
            rec["status"] = f"{type(e).__name__}: {str(e)[:80]}"
            print(f"  [{domain:<7}] 异常: {rec['status']}", flush=True)
        results.append(rec)


# ---------------------------------------------------------------- 主
def main():
    tiffs = sorted(f for f in os.listdir(TESTSET) if f.lower().endswith(".tiff"))
    pool = np.random.default_rng(20260923).integers(
        0, 256, TARGET_PAYLOAD, dtype=np.uint8).tobytes()
    print(f"测试图库 {len(tiffs)} 张 | 载荷池 {len(pool)}B 真随机 | 口令 {PASSWORD}")
    print(f"载荷池 zlib({TARGET_PAYLOAD}B) = {len(zlib.compress(pool,9))}B "
          f"-> 密文 {cipher_len(pool)}B (不可压缩, 开销 {CIPHER_FIXED+11}B)")

    results = []
    t_start = time.perf_counter()
    for fn in tiffs:
        run_one(fn.split("_", 1)[-1].replace(".tiff", ""),
                os.path.join(TESTSET, fn), results, pool)
    total = time.perf_counter() - t_start

    keys = ["image", "domain", "status", "capacity_bytes", "payload_bytes",
            "cipher_bytes", "overhead", "psnr_db", "ssim", "changed_pct",
            "max_delta", "embed_s", "extract_s", "roundtrip", "extract_size",
            "cover_bytes", "stego_bytes"]
    csv_p = os.path.join(OUTDIR, "baseline_results.csv")
    with open(csv_p, "w", encoding="utf-8-sig") as f:
        f.write(",".join(keys) + "\n")
        for r in results:
            f.write(",".join(
                f"{r.get(k):.6f}" if isinstance(r.get(k), float) else str(r.get(k, ""))
                for k in keys) + "\n")
    print(f"\n[CSV] {csv_p}")

    ok = [r for r in results if r.get("status") == "OK"]
    sp = [r for r in ok if r["domain"] == "spatial"]
    jp = [r for r in ok if r["domain"] == "jpeg"]
    rt_ok = [r for r in ok if r.get("roundtrip") == "OK"]

    md = [f"# hstego 评测基线数据表\n",
          f"> 生成时间 {time.strftime('%Y-%m-%d %H:%M:%S')}　总耗时 {total:.1f}s　"
          f"图源 USC-SIPI 标准库（{len(tiffs)} 张）\n",
          f"> 载荷 **真随机 {TARGET_PAYLOAD}B**（不可压缩）　口令 `{PASSWORD}`　"
          f"JPEG q={JPEG_QUALITY} 4:4:4　容量上限 5%\n",
          f"> 密文长度公式：`60 + len(zlib.compress(data, 9))`　"
          f"即不可压缩载荷需预留 **71 字节**开销\n",
          "\n## 一、空间域 S-UNIWARD（PNG 载体）\n",
          "| 图像 | 最大容量(B) | 载荷(B) | 密文(B) | PSNR(dB) | SSIM | 改动像素% | 嵌入(s) | 提取(s) | 往返 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sp:
        md.append(f"| {r['image']} | {r['capacity_bytes']} | {r['payload_bytes']} | "
                  f"{r['cipher_bytes']} | {r['psnr_db']:.2f} | {r['ssim']:.6f} | "
                  f"{r['changed_pct']:.3f} | {r['embed_s']:.1f} | {r['extract_s']:.1f} | "
                  f"{r['roundtrip']} |")

    md += ["\n## 二、压缩域 J-UNIWARD（JPEG q=90 4:4:4 载体）\n",
           "| 图像 | 最大容量(B) | 载荷(B) | 密文(B) | PSNR(dB) | SSIM | 改动像素% | 嵌入(s) | 提取(s) | 往返 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in jp:
        md.append(f"| {r['image']} | {r['capacity_bytes']} | {r['payload_bytes']} | "
                  f"{r['cipher_bytes']} | {r['psnr_db']:.2f} | {r['ssim']:.6f} | "
                  f"{r['changed_pct']:.3f} | {r['embed_s']:.1f} | {r['extract_s']:.1f} | "
                  f"{r['roundtrip']} |")

    md += ["\n## 三、汇总\n"]
    md.append(f"- 执行成功 {len(ok)}/{len(results)} 条"
              f"（空间域 {len(sp)} 条、压缩域 {len(jp)} 条）")
    if ok:
        md.append(f"- **往返一致率 {100.0*len(rt_ok)/len(ok):.0f}%**"
                  f"（{len(rt_ok)}/{len(ok)}）→ 存在确定性失败，**必须做嵌入后自检**")
    if sp:
        v = [r["psnr_db"] for r in sp]
        s = [r["ssim"] for r in sp]
        md.append(f"- 空间域 PSNR {min(v):.2f}–{max(v):.2f} dB（均 {sum(v)/len(v):.2f}）"
                  f"　SSIM 最低 {min(s):.6f}")
    if jp:
        v = [r["psnr_db"] for r in jp]
        s = [r["ssim"] for r in jp]
        md.append(f"- 压缩域 PSNR {min(v):.2f}–{max(v):.2f} dB（均 {sum(v)/len(v):.2f}）"
                  f"　SSIM 最低 {min(s):.6f}")
        c = {r["image"]: r["capacity_bytes"] for r in jp}
        md.append(f"- 压缩域容量最高载体 **{max(c, key=c.get)}**（{c[max(c, key=c.get)]}B）"
                  f"、最低 **{min(c, key=c.get)}**（{c[min(c, key=c.get)]}B）"
                  f" → 容量高度依赖图像内容，**不能用尺寸估算**")

    fails = [r for r in results if r.get("status") != "OK"]
    bad = [r for r in ok if r.get("roundtrip") != "OK"]
    if bad:
        md.append("\n## 四、往返失败条目（⚠️ 需在 GUI 中拦截）\n")
        for r in bad:
            md.append(f"- `{r['image']}` / {r['domain']}：容量 {r['capacity_bytes']}B，"
                      f"载荷仅 {r['payload_bytes']}B 仍提取失败")
        md.append("\n> 失败无法从载体属性（尺寸/容量/纹理）预测，且 `extract()` **不抛异常**、"
                  "只输出 0 字节文件。\n> 详见《J-UNIWARD可靠性缺陷报告.md》。"
                  "**GUI 必须在嵌入后立刻做一次往返自检。**")
    if fails:
        md.append("\n## 五、跳过/异常条目\n")
        for r in fails:
            md.append(f"- `{r['image']}` / {r['domain']}：{r['status']}")

    md_p = os.path.join(OUTDIR, "baseline_report.md")
    with open(md_p, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"[MD ] {md_p}")
    print(f"\n完成 {len(ok)}/{len(results)}　往返一致 {len(rt_ok)}/{len(ok)}　耗时 {total:.1f}s")


if __name__ == "__main__":
    main()
