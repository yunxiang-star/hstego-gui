"""隐写引擎抽象层。

这是实施计划 §5.4 的落点：把隐写引擎抽象成一层接口，接口的返回值**必须包含
"是否真的藏成功"**（`EmbedResult.verified`），因为 hstego 的 `embed()` 返回不代表
可提取（实测 JPEG 域 25% 失败）。

本月实现 `HStegoEngine`；将来加 `DiffusionEngine`（生成式隐写）时上层 API 不用改。
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# (stage_key, progress 0..1, 人类可读消息)
ProgressFn = Callable[[str, float, str], None]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_text(data: bytes, limit: int = 4096) -> tuple[bool, str | None]:
    """判断载荷是否是可当文本展示的内容。"""

    if not data:
        return False, None
    sample = data[:limit]
    if b"\x00" in sample:
        return False, None
    for encoding in ("utf-8", "gb18030"):
        try:
            text = sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        # 控制字符过多则不算文本
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
        if printable / max(1, len(text)) < 0.9:
            return False, None
        return True, text
    return False, None


@dataclass
class EngineInfo:
    """引擎自述信息，供 /api/v1/engines 与前端展示。"""

    name: str
    display_name: str
    available: bool
    kind: str  # "carrier"（有载体隐写） / "generative"（生成式隐写）
    domains: list[str]
    algorithms: list[str]
    notes: str = ""
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "available": self.available,
            "kind": self.kind,
            "domains": self.domains,
            "algorithms": self.algorithms,
            "notes": self.notes,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass
class CapacityReport:
    """容量口径（务必区分"密文预算"与"原始载荷上限"）。

    hstegolib 的 `jpg_capacity()` / `spatial_capacity()` 返回的是**密文预算**：
    密文长度 = 60 + len(zlib.compress(载荷, 9))，
    其中 60 = salt16 + nonce16 + tag16 + magic4 + len8。
    所以不可压缩载荷（随机数据、已压缩文件）实际只能塞进 `capacity_bytes - 60`。
    """

    engine: str
    domain: str
    algorithm: str
    capacity_bytes: int
    cipher_overhead_bytes: int
    max_incompressible_payload_bytes: int
    width: int | None = None
    height: int | None = None
    channels: int | None = None
    image_format: str | None = None
    payload_bytes: int | None = None
    payload_cipher_bytes: int | None = None
    payload_compression_ratio: float | None = None
    fits: bool | None = None
    utilization: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "domain": self.domain,
            "algorithm": self.algorithm,
            "capacity_bytes": self.capacity_bytes,
            "cipher_overhead_bytes": self.cipher_overhead_bytes,
            "max_incompressible_payload_bytes": self.max_incompressible_payload_bytes,
            "width": self.width,
            "height": self.height,
            "channels": self.channels,
            "image_format": self.image_format,
            "payload_bytes": self.payload_bytes,
            "payload_cipher_bytes": self.payload_cipher_bytes,
            "payload_compression_ratio": (
                None
                if self.payload_compression_ratio is None
                else round(self.payload_compression_ratio, 6)
            ),
            "fits": self.fits,
            "utilization": (
                None if self.utilization is None else round(self.utilization, 6)
            ),
            "notes": self.notes,
        }


@dataclass
class EmbedAttempt:
    """一次尝试（首次 + 每次重试）的完整记录。前端要能展示"试了几次、为什么失败"。"""

    index: int
    quality: int | None
    cover_path: str
    cover_bytes: int
    cover_used_bytes: int
    capacity_bytes: int
    payload_cipher_bytes: int
    capacity_ok: bool
    embed_ok: bool
    embed_error: str | None
    verified: bool
    failure_reason: str | None
    stego_path: str | None
    stego_bytes: int | None
    warnings: list[str]
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "quality": self.quality,
            "cover_used_bytes": self.cover_used_bytes,
            "capacity_bytes": self.capacity_bytes,
            "payload_cipher_bytes": self.payload_cipher_bytes,
            "capacity_ok": self.capacity_ok,
            "embed_ok": self.embed_ok,
            "embed_error": self.embed_error,
            "verified": self.verified,
            "failure_reason": self.failure_reason,
            "stego_bytes": self.stego_bytes,
            "warnings": self.warnings,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


@dataclass
class EmbedResult:
    """嵌入结果。

    `ok` 与 `verified` 的区别：
      - `ok`      = 整条流水线可用（载密图存在且自检通过）
      - `verified`= 嵌入后自检（立刻 extract 回来比对 sha256）是否通过
    只有当 `verified` 为 True 时，载密图才是**真的能取回消息**的。
    """

    ok: bool
    verified: bool
    engine: str
    domain: str
    algorithm: str
    capacity: CapacityReport
    payload_bytes: int
    payload_sha256: str
    attempts: list[EmbedAttempt]
    chosen_attempt: int | None
    cover_path: str
    cover_sha256: str
    stego_path: str | None
    stego_bytes: int | None
    stego_sha256: str | None
    metrics: dict[str, Any] | None
    metrics_vs_original: dict[str, Any] | None
    warnings: list[str]
    elapsed_seconds: float
    message: str
    hint: str | None = None
    is_text: bool = False
    text_preview: str | None = None
    cover_used_path: str | None = None
    cover_used_sha256: str | None = None
    diff_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verified": self.verified,
            "engine": self.engine,
            "domain": self.domain,
            "algorithm": self.algorithm,
            "capacity": self.capacity.to_dict(),
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
            "attempts": [a.to_dict() for a in self.attempts],
            "chosen_attempt": self.chosen_attempt,
            "cover_sha256": self.cover_sha256,
            "cover_used_sha256": self.cover_used_sha256,
            "stego_bytes": self.stego_bytes,
            "stego_sha256": self.stego_sha256,
            "metrics": self.metrics,
            "metrics_vs_original": self.metrics_vs_original,
            "warnings": self.warnings,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "message": self.message,
            "hint": self.hint,
            "is_text": self.is_text,
            "text_preview": self.text_preview,
            "has_diff_image": self.diff_path is not None,
        }


@dataclass
class ExtractResult:
    """提取结果。

    ⚠️ hstego 里"口令错误 / 图中没有消息 / 提取失败"三者症状完全相同
    （0 字节输出 + 一行 stdout WARNING），所以 `reason` 用 `not_found`
    而不是 `wrong_password`，前端文案也必须三者并列陈述。
    """

    ok: bool
    reason: str  # "ok" | "not_found" | "unsupported_format" | "invalid_image" | "engine_error"
    engine: str
    domain: str
    algorithm: str
    payload_path: str | None
    payload_bytes: int
    payload_sha256: str | None
    is_text: bool
    text: str | None
    text_truncated: bool
    filename_hint: str | None
    stego_sha256: str
    stego_bytes: int
    warnings: list[str]
    elapsed_seconds: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "engine": self.engine,
            "domain": self.domain,
            "algorithm": self.algorithm,
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
            "is_text": self.is_text,
            "text": self.text,
            "text_truncated": self.text_truncated,
            "filename_hint": self.filename_hint,
            "stego_sha256": self.stego_sha256,
            "stego_bytes": self.stego_bytes,
            "warnings": self.warnings,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "message": self.message,
        }


class StegoEngine(ABC):
    """隐写引擎接口。

    上层（FastAPI 路由 / 未来前端）只依赖这四个方法。
    换成生成式引擎时，只要实现同样的签名即可，上层不改。
    """

    name: str = "base"
    display_name: str = "Base Engine"

    @abstractmethod
    def info(self) -> EngineInfo:
        """自述信息与可用性。"""

    @abstractmethod
    def capacity(
        self,
        cover_path: str | Path,
        payload_path: str | Path | None = None,
    ) -> CapacityReport:
        """算容量。给了 payload 就按**实际文件**算能不能装下。"""

    @abstractmethod
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
        """嵌入，并在返回前完成自检。"""

    @abstractmethod
    def extract(
        self,
        stego_path: str | Path,
        key: str,
        out_path: str | Path,
        *,
        progress: ProgressFn | None = None,
        text_preview_chars: int = 2000,
    ) -> ExtractResult:
        """提取。"""
