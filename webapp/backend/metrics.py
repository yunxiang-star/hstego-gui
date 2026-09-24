"""图像质量指标：PSNR / SSIM / 差分统计与差分放大图。

不引入 scikit-image，只用 numpy + scipy，避免给工程加新依赖。
SSIM 采用 Wang et al. 2004 的标准实现（11×11 高斯窗，sigma=1.5，
K1=0.01, K2=0.03），灰度权重 0.299/0.587/0.114。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import scipy.ndimage
from PIL import Image

SSIM_K1 = 0.01
SSIM_K2 = 0.03
SSIM_WINDOW = 11
SSIM_SIGMA = 1.5


@dataclass
class QualityMetrics:
    """载体 vs 载密的质量对比。"""

    psnr_db: float | None
    ssim: float | None
    mse: float
    identical: bool
    max_abs_diff: int
    mean_abs_diff: float
    changed_samples: int
    total_samples: int
    changed_ratio: float
    shape: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "psnr_db": None if self.psnr_db is None else round(self.psnr_db, 4),
            "ssim": None if self.ssim is None else round(self.ssim, 8),
            "mse": round(self.mse, 8),
            "identical": self.identical,
            "max_abs_diff": self.max_abs_diff,
            "mean_abs_diff": round(self.mean_abs_diff, 8),
            "changed_samples": self.changed_samples,
            "total_samples": self.total_samples,
            "changed_ratio": round(self.changed_ratio, 8),
            "shape": self.shape,
        }


def load_image_array(path: str | Path) -> np.ndarray:
    """读图成 uint8 数组（RGB 或灰度），失败时抛 OSError/ValueError。"""

    with Image.open(path) as img:
        img.load()
        if img.mode in ("P", "PA"):
            img = img.convert("RGBA")
        if img.mode == "RGBA":
            # 丢掉 alpha，与 hstegolib 的通道处理保持一致（它按 RGB 处理）
            arr = np.asarray(img.convert("RGB"))
        elif img.mode in ("L", "I;16", "I", "F"):
            arr = np.asarray(img)
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
        else:
            arr = np.asarray(img.convert("RGB"))
    return np.ascontiguousarray(arr)


def _to_gray(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        return arr.astype(np.float64)
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float64)
    return (arr[..., :3].astype(np.float64) * weights).sum(axis=-1)


def _gaussian_window(size: int = SSIM_WINDOW, sigma: float = SSIM_SIGMA) -> np.ndarray:
    coords = np.arange(size, dtype=np.float64) - (size - 1) / 2.0
    kernel = np.exp(-(coords**2) / (2.0 * sigma**2))
    kernel /= kernel.sum()
    return np.outer(kernel, kernel)


def compute_ssim(a: np.ndarray, b: np.ndarray, data_range: float = 255.0) -> float:
    """全图平均 SSIM。输入需同形状（可为灰度或彩色）。"""

    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} != {b.shape}")

    x = _to_gray(a)
    y = _to_gray(b)

    window = _gaussian_window()
    c1 = (SSIM_K1 * data_range) ** 2
    c2 = (SSIM_K2 * data_range) ** 2

    mu_x = scipy.ndimage.convolve(x, window, mode="reflect")
    mu_y = scipy.ndimage.convolve(y, window, mode="reflect")
    mu_x_sq = mu_x * mu_x
    mu_y_sq = mu_y * mu_y
    mu_xy = mu_x * mu_y

    sigma_x_sq = scipy.ndimage.convolve(x * x, window, mode="reflect") - mu_x_sq
    sigma_y_sq = scipy.ndimage.convolve(y * y, window, mode="reflect") - mu_y_sq
    sigma_xy = scipy.ndimage.convolve(x * y, window, mode="reflect") - mu_xy

    numerator = (2.0 * mu_xy + c1) * (2.0 * sigma_xy + c2)
    denominator = (mu_x_sq + mu_y_sq + c1) * (sigma_x_sq + sigma_y_sq + c2)
    ssim_map = numerator / denominator
    return float(ssim_map.mean())


def compute_psnr(a: np.ndarray, b: np.ndarray, peak: float = 255.0) -> float | None:
    """PSNR（dB）。完全相同时返回 None（数学上是 +inf，JSON 表达不了）。"""

    diff = a.astype(np.float64) - b.astype(np.float64)
    mse = float(np.mean(diff * diff))
    if mse == 0.0:
        return None
    return 10.0 * math.log10((peak * peak) / mse)


def compare(cover: np.ndarray, stego: np.ndarray, with_ssim: bool = True) -> QualityMetrics:
    """算一组完整指标。形状不一致时抛 ValueError。"""

    if cover.shape != stego.shape:
        raise ValueError(f"shape mismatch: {cover.shape} != {stego.shape}")

    diff = cover.astype(np.int16) - stego.astype(np.int16)
    abs_diff = np.abs(diff)
    total = int(abs_diff.size)
    changed = int(np.count_nonzero(abs_diff))
    mse = float(np.mean(diff.astype(np.float64) ** 2))

    return QualityMetrics(
        psnr_db=compute_psnr(cover, stego),
        ssim=compute_ssim(cover, stego) if with_ssim else None,
        mse=mse,
        identical=changed == 0,
        max_abs_diff=int(abs_diff.max()) if total else 0,
        mean_abs_diff=float(abs_diff.mean()) if total else 0.0,
        changed_samples=changed,
        total_samples=total,
        changed_ratio=(changed / total) if total else 0.0,
        shape=list(cover.shape),
    )


def save_diff_image(
    cover: np.ndarray,
    stego: np.ndarray,
    out_path: str | Path,
    gain: int = 20,
) -> Path:
    """输出"像素差值 ×gain"的可视化 PNG（差分放大视图）。

    UNIWARD 单点改动通常只有 ±1，直接看差分图是纯黑，
    放大 20 倍后人眼才能看到代价函数选择的位置分布。
    """

    if cover.shape != stego.shape:
        raise ValueError(f"shape mismatch: {cover.shape} != {stego.shape}")

    diff = np.abs(cover.astype(np.int16) - stego.astype(np.int16)).astype(np.int32)
    amplified = np.clip(diff * max(1, int(gain)), 0, 255).astype(np.uint8)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(amplified).save(out_path, format="PNG", optimize=True)
    return out_path
