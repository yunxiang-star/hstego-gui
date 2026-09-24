"""HStegoEngine —— 对 hstegolib 的产品化封装。

它比官方 API 多出来的三件事，正是本项目相对上游 GUI 的差异化（实施计划 §5.1）：

1. **嵌入后往返自检**（`EmbedResult.verified`）——嵌入完立刻自己 extract 一次，
   按「输出不存在 / 0 字节 / sha256 不符」判定，**不靠 try/except**
   （hstego 的 extract 失败时静默写 0 字节，永不抛异常）。
2. **失败自动换参重试**——JPEG 域按 `q95 → q92 → q88` 重编码载体后重试，
   全程记录到 `attempts[]`，对上层与用户都可见。
3. **真容量的口径**——容量按「密文长度 = 60 + len(zlib.compress(载荷, 9))」算，
   而不是拿 `jpg_capacity()` 的数字直接当"能藏多少字节"，避免用户按它选文件就撞
   `ValueError: Message too long`。

并发约束：hstegolib 用模块级 `random.seed()` + `random.shuffle()` 选嵌入位置，
**不是线程安全的**。所有原生调用都在 `_ENGINE_LOCK` 里串行执行。
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from PIL import Image

from .. import metrics as metrics_mod
from ..errors import AppError, EngineUnavailableError, ImageTooLargeError
from .base import (
    CapacityReport,
    EmbedAttempt,
    EmbedResult,
    EngineInfo,
    ExtractResult,
    ProgressFn,
    StegoEngine,
    sha256_bytes,
    sha256_file,
    sniff_text,
)

# hstego 里密文比明文多出的固定开销：salt16 + nonce16 + tag16 + magic4 + len8
DEFAULT_CIPHER_OVERHEAD = 60

SPATIAL_OUTPUT_SUFFIX = ".png"
JPEG_OUTPUT_SUFFIX = ".jpg"

_ENGINE_LOCK = threading.RLock()
_IMPORT_LOCK = threading.Lock()
_HSTEGOLIB: Any = None
_IMPORT_ERROR: str | None = None


def _import_hstegolib(project_root: Path) -> tuple[Any, str | None]:
    """把工程根加进 sys.path 后导入 hstegolib。只做一次，结果缓存。"""

    global _HSTEGOLIB, _IMPORT_ERROR
    with _IMPORT_LOCK:
        if _HSTEGOLIB is not None:
            return _HSTEGOLIB, None
        if _IMPORT_ERROR is not None:
            return None, _IMPORT_ERROR
        root = str(project_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            import hstegolib  # type: ignore

            _HSTEGOLIB = hstegolib
            return hstegolib, None
        except Exception as exc:  # noqa: BLE001 - 原生扩展缺失会抛各种异常
            _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
            return None, _IMPORT_ERROR


def _cipher_overhead(hstegolib: Any) -> int:
    try:
        from Crypto.Cipher import AES  # type: ignore

        return (
            AES.block_size * 3
            + int(getattr(hstegolib, "CIPHER_HEADER_SIZE", 12))
        )
    except Exception:  # noqa: BLE001
        return DEFAULT_CIPHER_OVERHEAD


def _cipher_len(data: bytes, overhead: int) -> int:
    """复刻 hstegolib.Cipher.encrypt 的长度公式：overhead + len(zlib.compress(data, 9))。"""

    return overhead + len(zlib.compress(data, 9))


class _StdoutCapture:
    """捕获 hstegolib 打在 stdout 上的 WARNING（它不打 stderr）。

    只在持有 _ENGINE_LOCK 时使用，否则会串到别的线程去。
    """

    def __init__(self) -> None:
        self._buffer = io.StringIO()

    def __enter__(self) -> "_StdoutCapture":
        self._ctx = contextlib.redirect_stdout(self._buffer)
        self._ctx.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._ctx.__exit__(*exc_info)

    @property
    def lines(self) -> list[str]:
        raw = self._buffer.getvalue().splitlines()
        return [line.strip() for line in raw if line.strip()]

    @property
    def warnings(self) -> list[str]:
        return [line for line in self.lines if "WARNING" in line.upper()]


class HStegoEngine(StegoEngine):
    """UNIWARD + STC 有载体隐写引擎（hstego v0.6.1）。"""

    name = "hstego"
    display_name = "HStego（UNIWARD + STC）"

    def __init__(self, project_root: Path, config: dict[str, Any] | None = None) -> None:
        self.project_root = Path(project_root)
        cfg = dict(config or {})
        self.jpeg_retry_qualities: tuple[int, ...] = tuple(
            cfg.get("jpeg_retry_qualities", (95, 92, 88))
        )
        self.jpeg_subsampling: int = int(cfg.get("jpeg_subsampling", 0))
        self.max_attempts: int = int(cfg.get("max_embed_attempts", 4))
        self.max_upload_bytes: int = int(cfg.get("max_upload_bytes", 64 * 1024 * 1024))
        self.max_payload_bytes: int = int(
            cfg.get("max_payload_bytes", 8 * 1024 * 1024)
        )
        self.with_ssim: bool = bool(cfg.get("with_ssim", True))
        self._hstegolib, self._import_error = _import_hstegolib(self.project_root)

    # ------------------------------------------------------------------ info

    @property
    def available(self) -> bool:
        return self._hstegolib is not None

    def require(self) -> Any:
        if self._hstegolib is None:
            raise EngineUnavailableError(
                "hstegolib 导入失败（原生扩展未编译或 Python 环境不匹配）",
                detail={"import_error": self._import_error},
            )
        return self._hstegolib

    def info(self) -> EngineInfo:
        notes = [
            f"容量上限 MAX_PAYLOAD = {getattr(self._hstegolib, 'MAX_PAYLOAD', 0.05)}"
            if self.available
            else "",
            "JPEG 域存在上游已知缺陷：提取会静默失败（实测 ~25%），"
            "本引擎以「嵌入后自检 + 失败重试」兜住",
        ]
        return EngineInfo(
            name=self.name,
            display_name=self.display_name,
            available=self.available,
            kind="carrier",
            domains=["spatial", "jpeg"],
            algorithms=["S-UNIWARD", "J-UNIWARD"],
            notes=" ｜ ".join(part for part in notes if part),
            unavailable_reason=self._import_error,
        )

    # -------------------------------------------------------------- 域判定

    def detect_domain(self, path: str | Path) -> tuple[str, str]:
        """返回 (domain, algorithm)。domain ∈ {spatial, jpeg}。"""

        path = Path(path)
        try:
            with Image.open(path) as img:
                fmt = (img.format or "").upper()
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                f"无法解析图像：{path.name}",
                code="invalid_image",
                status_code=400,
                detail={"error": f"{type(exc).__name__}: {exc}"},
            ) from exc

        if fmt in ("JPEG", "MPO"):
            return "jpeg", "J-UNIWARD"
        return "spatial", "S-UNIWARD"

    def output_suffix(self, domain: str) -> str:
        return JPEG_OUTPUT_SUFFIX if domain == "jpeg" else SPATIAL_OUTPUT_SUFFIX

    # -------------------------------------------------------------- capacity

    def capacity(
        self,
        cover_path: str | Path,
        payload_path: str | Path | None = None,
    ) -> CapacityReport:
        hstegolib = self.require()
        cover_path = Path(cover_path)
        self._check_size(cover_path)

        domain, algorithm = self.detect_domain(cover_path)
        overhead = _cipher_overhead(hstegolib)

        width = height = None
        channels = None
        image_format = None
        with Image.open(cover_path) as img:
            width, height = img.size
            image_format = img.format
            channels = len(img.getbands())

        started = time.perf_counter()
        with _ENGINE_LOCK, _StdoutCapture() as capture:
            if domain == "jpeg":
                jpg = hstegolib.jpeg_load(str(cover_path))
                capacity_bytes = int(hstegolib.jpg_capacity(jpg))
                del jpg
            else:
                arr = metrics_mod.load_image_array(cover_path)
                capacity_bytes = int(hstegolib.spatial_capacity(arr))
                del arr
        elapsed = time.perf_counter() - started

        notes = [
            "capacity_bytes 是**密文预算**，不是原始载荷上限。",
            f"密文长度 = {overhead} + len(zlib.compress(载荷, 9))。",
        ]
        if self._toolbox_missing(capture):
            notes.append("提示：JPEG 域的载荷通常可被 zlib 压缩，纯文本能藏得比估的更多。")

        report = CapacityReport(
            engine=self.name,
            domain=domain,
            algorithm=algorithm,
            capacity_bytes=capacity_bytes,
            cipher_overhead_bytes=overhead,
            max_incompressible_payload_bytes=max(0, capacity_bytes - overhead),
            width=width,
            height=height,
            channels=channels,
            image_format=image_format,
            notes=notes,
        )

        if payload_path is not None:
            payload_path = Path(payload_path)
            self._check_size(payload_path, is_payload=True)
            data = payload_path.read_bytes()
            cipher_len = _cipher_len(data, overhead)
            report.payload_bytes = len(data)
            report.payload_cipher_bytes = cipher_len
            report.payload_compression_ratio = (
                cipher_len / len(data) if data else None
            )
            report.fits = cipher_len <= capacity_bytes
            report.utilization = (
                cipher_len / capacity_bytes if capacity_bytes else None
            )

        _ = elapsed  # 保留计时供后续 /health 扩展
        return report

    @staticmethod
    def _toolbox_missing(capture: _StdoutCapture) -> bool:
        return any("JPEG Toolbox" in line for line in capture.lines)

    # ----------------------------------------------------------------- embed

    def embed(
        self,
        cover_path: str | Path,
        payload_path: str | Path,
        key: str,
        out_path: str | Path,
        *,
        options: dict[str, Any] | None = None,
        progress: ProgressFn | None = None,
    ) -> EmbedResult:
        hstegolib = self.require()
        opts = dict(options or {})
        cover_path = Path(cover_path)
        payload_path = Path(payload_path)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        self._check_size(cover_path)
        self._check_size(payload_path, is_payload=True)

        notify = progress or (lambda *_: None)
        started = time.perf_counter()

        notify("prepare", 0.02, "校验载体与载荷")
        domain, algorithm = self.detect_domain(cover_path)
        overhead = _cipher_overhead(hstegolib)

        payload = payload_path.read_bytes()
        payload_sha = sha256_bytes(payload)
        cipher_len = _cipher_len(payload, overhead)
        is_text, text_preview = sniff_text(payload)
        original_cover_sha = sha256_file(cover_path)

        notify("capacity", 0.08, "计算容量与编码预算")
        capacity_report = self.capacity(cover_path, payload_path)

        warnings: list[str] = []
        attempts: list[EmbedAttempt] = []
        chosen: int | None = None
        chosen_stego: Path | None = None
        chosen_cover: Path | None = None

        for index in range(self.max_attempts):
            ladder = self.jpeg_retry_qualities if domain == "jpeg" else ()
            if index == 0:
                quality: int | None = None
            elif index - 1 < len(ladder):
                quality = int(ladder[index - 1])
            else:
                break

            label = "原始载体" if quality is None else f"重编码 q{quality}"
            notify(
                "embed",
                0.10 + 0.20 * index,
                f"第 {index + 1} 次嵌入（{label}）",
            )

            attempt_cover = cover_path
            if quality is not None:
                attempt_cover = out_path.parent / f"{out_path.stem}.cover_q{quality}.jpg"
                self._reencode_jpeg(cover_path, attempt_cover, quality)

            attempt_dir = out_path.parent / f"attempt{index}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            attempt_stego = attempt_dir / f"stego{self.output_suffix(domain)}"
            attempt_check = attempt_dir / "selfcheck.bin"

            t0 = time.perf_counter()
            attempt = EmbedAttempt(
                index=index,
                quality=quality,
                cover_path=str(attempt_cover),
                cover_bytes=cover_path.stat().st_size,
                cover_used_bytes=attempt_cover.stat().st_size,
                capacity_bytes=capacity_report.capacity_bytes,
                payload_cipher_bytes=cipher_len,
                capacity_ok=cipher_len <= capacity_report.capacity_bytes,
                embed_ok=False,
                embed_error=None,
                verified=False,
                failure_reason=None,
                stego_path=None,
                stego_bytes=None,
                warnings=[],
                elapsed_seconds=0.0,
            )

            # 若重编码后容量不够，直接跳过这一档（记为容量不足，而不是嵌入失败）
            if quality is not None:
                with _ENGINE_LOCK, _StdoutCapture() as capture:
                    if domain == "jpeg":
                        attempt_capacity = int(
                            hstegolib.jpg_capacity(hstegolib.jpeg_load(str(attempt_cover)))
                        )
                    else:
                        attempt_capacity = int(
                            hstegolib.spatial_capacity(
                                metrics_mod.load_image_array(attempt_cover)
                            )
                        )
                attempt.capacity_bytes = attempt_capacity
                attempt.capacity_ok = cipher_len <= attempt_capacity
                attempt.warnings.extend(capture.warnings)
                if not attempt.capacity_ok:
                    attempt.failure_reason = "insufficient_capacity"
                    attempt.elapsed_seconds = time.perf_counter() - t0
                    attempts.append(attempt)
                    notify(
                        "embed",
                        0.10 + 0.20 * index,
                        f"{label} 容量不足（{attempt_capacity} < {cipher_len}），跳过",
                    )
                    continue
            elif not attempt.capacity_ok:
                attempt.failure_reason = "insufficient_capacity"
                attempt.elapsed_seconds = time.perf_counter() - t0
                attempts.append(attempt)
                raise AppError(
                    f"载荷超出载体容量：需要 {cipher_len} 字节密文，"
                    f"该载体只能放 {capacity_report.capacity_bytes} 字节",
                    code="payload_too_large",
                    status_code=413,
                    detail={
                        "payload_cipher_bytes": cipher_len,
                        "capacity_bytes": capacity_report.capacity_bytes,
                    },
                )

            embedder = hstegolib.J_UNIWARD() if domain == "jpeg" else hstegolib.S_UNIWARD()

            try:
                with _ENGINE_LOCK, _StdoutCapture() as capture:
                    embedder.embed(
                        str(attempt_cover),
                        str(payload_path),
                        key,
                        str(attempt_stego),
                    )
                attempt.embed_ok = attempt_stego.exists()
                attempt.warnings.extend(capture.warnings)
                warnings.extend(capture.warnings)
            except Exception as exc:  # noqa: BLE001
                attempt.embed_ok = False
                attempt.embed_error = f"{type(exc).__name__}: {exc}"
                attempt.failure_reason = "embed_error"
                attempt.elapsed_seconds = time.perf_counter() - t0
                attempts.append(attempt)
                warnings.append(f"attempt{index} 嵌入异常：{attempt.embed_error}")
                continue

            attempt.stego_path = str(attempt_stego)
            attempt.stego_bytes = attempt_stego.stat().st_size

            # ---- 自检：立刻 extract 一次并比对 sha256（不能靠 try/except）
            notify(
                "verify",
                0.30 + 0.20 * index,
                "自检：立刻提取并比对 sha256",
            )
            verified, reason = self._self_check(
                hstegolib, domain, attempt_stego, key, attempt_check, payload_sha
            )
            attempt.verified = verified
            if not verified:
                attempt.failure_reason = reason

            attempt.elapsed_seconds = time.perf_counter() - t0
            attempts.append(attempt)

            if verified:
                chosen = index
                chosen_stego = attempt_stego
                chosen_cover = attempt_cover
                break

            notify(
                "verify",
                0.30 + 0.20 * index,
                f"第 {index + 1} 次自检未通过（{reason}），准备重试",
            )

        if chosen is None or chosen_stego is None or chosen_cover is None:
            hint = self._failure_hint(domain, attempts)
            return EmbedResult(
                ok=False,
                verified=False,
                engine=self.name,
                domain=domain,
                algorithm=algorithm,
                capacity=capacity_report,
                payload_bytes=len(payload),
                payload_sha256=payload_sha,
                attempts=attempts,
                chosen_attempt=None,
                cover_path=str(cover_path),
                cover_sha256=original_cover_sha,
                stego_path=None,
                stego_bytes=None,
                stego_sha256=None,
                metrics=None,
                metrics_vs_original=None,
                warnings=warnings,
                elapsed_seconds=time.perf_counter() - started,
                message="嵌入未通过自检：载密图无法保证被正确提取，已放弃输出。",
                hint=hint,
                is_text=is_text,
                text_preview=text_preview,
            )

        # ---------------------------------------------------------- 收尾：指标 + 差分图
        notify("metrics", 0.85, "计算 PSNR / SSIM 与差分视图")
        final_stego = out_path.with_suffix(self.output_suffix(domain))
        shutil.copyfile(chosen_stego, final_stego)

        cover_arr = metrics_mod.load_image_array(chosen_cover)
        stego_arr = metrics_mod.load_image_array(final_stego)
        quality_metrics = None
        if cover_arr.shape == stego_arr.shape:
            quality_metrics = metrics_mod.compare(
                cover_arr, stego_arr, with_ssim=self.with_ssim
            ).to_dict()

        metrics_vs_original = None
        diff_path: str | None = None
        try:
            original_arr = metrics_mod.load_image_array(cover_path)
            if original_arr.shape == stego_arr.shape:
                metrics_vs_original = metrics_mod.compare(
                    original_arr, stego_arr, with_ssim=self.with_ssim
                ).to_dict()
                if opts.get("include_diff", True) and opts.get("diff_path"):
                    gain = int(opts.get("diff_gain", 20))
                    metrics_mod.save_diff_image(
                        original_arr, stego_arr, Path(opts["diff_path"]), gain=gain
                    )
                    diff_path = str(opts["diff_path"])
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"差分图生成失败：{type(exc).__name__}: {exc}")

        elapsed = time.perf_counter() - started
        notify("done", 1.0, "嵌入完成并已通过自检")

        message = (
            f"嵌入成功并已通过自检（第 {chosen + 1} 次尝试，"
            f"{'原始载体' if attempts[chosen].quality is None else f'q{attempts[chosen].quality}'}）"
        )
        return EmbedResult(
            ok=True,
            verified=True,
            engine=self.name,
            domain=domain,
            algorithm=algorithm,
            capacity=capacity_report,
            payload_bytes=len(payload),
            payload_sha256=payload_sha,
            attempts=attempts,
            chosen_attempt=chosen,
            cover_path=str(cover_path),
            cover_sha256=original_cover_sha,
            cover_used_path=str(chosen_cover),
            cover_used_sha256=sha256_file(chosen_cover),
            stego_path=str(final_stego),
            stego_bytes=final_stego.stat().st_size,
            stego_sha256=sha256_file(final_stego),
            metrics=quality_metrics,
            metrics_vs_original=metrics_vs_original,
            warnings=warnings,
            elapsed_seconds=elapsed,
            message=message,
            hint=None,
            is_text=is_text,
            text_preview=text_preview,
            diff_path=diff_path,
        )

    # --------------------------------------------------------------- extract

    def extract(
        self,
        stego_path: str | Path,
        key: str,
        out_path: str | Path,
        *,
        progress: ProgressFn | None = None,
        text_preview_chars: int = 2000,
    ) -> ExtractResult:
        hstegolib = self.require()
        stego_path = Path(stego_path)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        notify = progress or (lambda *_: None)
        started = time.perf_counter()

        self._check_size(stego_path)
        notify("extract", 0.2, "解析载密图")
        domain, algorithm = self.detect_domain(stego_path)
        stego_sha = sha256_file(stego_path)

        extractor = hstegolib.J_UNIWARD() if domain == "jpeg" else hstegolib.S_UNIWARD()

        warnings: list[str] = []
        with contextlib.suppress(OSError):
            out_path.unlink()

        try:
            notify("extract", 0.4, "提取并解密")
            with _ENGINE_LOCK, _StdoutCapture() as capture:
                extractor.extract(str(stego_path), key, str(out_path))
            warnings.extend(capture.warnings)
        except Exception as exc:  # noqa: BLE001
            return ExtractResult(
                ok=False,
                reason="engine_error",
                engine=self.name,
                domain=domain,
                algorithm=algorithm,
                payload_path=None,
                payload_bytes=0,
                payload_sha256=None,
                is_text=False,
                text=None,
                text_truncated=False,
                filename_hint=None,
                stego_sha256=stego_sha,
                stego_bytes=stego_path.stat().st_size,
                warnings=warnings + [f"{type(exc).__name__}: {exc}"],
                elapsed_seconds=time.perf_counter() - started,
                message=f"提取过程异常：{type(exc).__name__}: {exc}",
            )

        # 失败判定：不存在 / 0 字节。hstego 失败时静默写空文件。
        if not out_path.exists() or out_path.stat().st_size == 0:
            data = b""
        else:
            data = out_path.read_bytes()

        if not data:
            notify("done", 1.0, "未提取到消息")
            return ExtractResult(
                ok=False,
                reason="not_found",
                engine=self.name,
                domain=domain,
                algorithm=algorithm,
                payload_path=None,
                payload_bytes=0,
                payload_sha256=None,
                is_text=False,
                text=None,
                text_truncated=False,
                filename_hint=None,
                stego_sha256=stego_sha,
                stego_bytes=stego_path.stat().st_size,
                warnings=warnings,
                elapsed_seconds=time.perf_counter() - started,
                message=(
                    "未提取到消息。可能原因：① 口令错误；"
                    "② 该图片中确实没有消息；③ 提取失败"
                    "（上游 JPEG 域存在静默失败，且这三种症状完全相同，无法从现象区分）。"
                ),
            )

        is_text, full_text = sniff_text(data, limit=max(text_preview_chars * 2, 4096))
        text_value = None
        truncated = False
        if is_text:
            decoded = data.decode("utf-8", errors="replace")
            if len(decoded) > text_preview_chars:
                text_value = decoded[:text_preview_chars]
                truncated = True
            else:
                text_value = decoded
        _ = full_text

        notify("done", 1.0, "提取完成")
        return ExtractResult(
            ok=True,
            reason="ok",
            engine=self.name,
            domain=domain,
            algorithm=algorithm,
            payload_path=str(out_path),
            payload_bytes=len(data),
            payload_sha256=sha256_bytes(data),
            is_text=is_text,
            text=text_value,
            text_truncated=truncated,
            filename_hint=None,
            stego_sha256=stego_sha,
            stego_bytes=stego_path.stat().st_size,
            warnings=warnings,
            elapsed_seconds=time.perf_counter() - started,
            message="提取成功。",
        )

    # ---------------------------------------------------------------- helpers

    def _self_check(
        self,
        hstegolib: Any,
        domain: str,
        stego_path: Path,
        key: str,
        check_path: Path,
        expected_sha256: str,
    ) -> tuple[bool, str | None]:
        """嵌入后往返自检。

        判定三连：输出不存在 / 0 字节 / sha256 不符 → 失败。
        **不使用 try/except 作为判据**，因为 hstego 的 extract 不抛异常。
        """

        with contextlib.suppress(OSError):
            check_path.unlink()

        extractor = hstegolib.J_UNIWARD() if domain == "jpeg" else hstegolib.S_UNIWARD()
        try:
            with _ENGINE_LOCK, _StdoutCapture():
                extractor.extract(str(stego_path), key, str(check_path))
        except Exception as exc:  # noqa: BLE001
            return False, f"extract_exception:{type(exc).__name__}"

        if not check_path.exists():
            return False, "empty_output"
        if check_path.stat().st_size == 0:
            return False, "empty_output"

        actual = sha256_file(check_path)
        if actual != expected_sha256:
            return False, "sha256_mismatch"
        return True, None

    def _reencode_jpeg(self, src: Path, dst: Path, quality: int) -> Path:
        with Image.open(src) as img:
            rgb = img.convert("RGB")
            dst.parent.mkdir(parents=True, exist_ok=True)
            rgb.save(
                dst,
                format="JPEG",
                quality=int(quality),
                subsampling=int(self.jpeg_subsampling),
            )
        return dst

    def _check_size(self, path: Path, is_payload: bool = False) -> None:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise AppError(
                f"文件不存在：{path.name}",
                code="missing_parameter",
                status_code=400,
                detail={"error": str(exc)},
            ) from exc
        limit = self.max_upload_bytes
        if is_payload:
            return
        if size > limit:
            raise ImageTooLargeError(
                f"文件过大：{size} 字节 > 上限 {limit} 字节",
                detail={"size": size, "limit": limit},
            )

    @staticmethod
    def _failure_hint(domain: str, attempts: list[EmbedAttempt]) -> str:
        reasons = {a.failure_reason for a in attempts}
        if "insufficient_capacity" in reasons and len(reasons) == 1:
            return "所有尝试都卡在容量上：请换更大的载体，或压缩载荷后再试。"
        if domain == "jpeg":
            return (
                "JPEG 域在上游实现中存在静默提取失败的缺陷（实测失败率约 25%，"
                "与载体和载荷都相关且无法事先预测）。已按 "
                "q95 → q92 → q88 逐档重编码重试仍失败，建议换一张纹理更丰富的载体图，"
                "或改用 PNG 载体走空间域（S-UNIWARD 在标准图库上 9/9 通过）。"
            )
        return (
            "空间域也未能通过自检，这在标准图库上极罕见。请换一张载体图重试；"
            "若持续复现，请把该载体与载荷留存，作为可复现案例归档。"
        )


def cleanup_paths(paths: list[Path]) -> None:
    """删除临时文件/目录（容错）。"""

    for path in paths:
        if not path.exists():
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        except OSError:
            pass
