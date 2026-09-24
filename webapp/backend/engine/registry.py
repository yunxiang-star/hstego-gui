"""引擎注册表。

本月只有 `hstego`（有载体隐写）一个可用引擎；`diffusion`（生成式隐写）作为
占位注册，用于证明 §5.4 的接口设计确实留出了课题第二阶段的接入位——
将来实现 `DiffusionEngine` 时，路由与前端都不用改。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..config import Settings
from ..errors import EngineUnavailableError
from .base import (
    CapacityReport,
    EmbedResult,
    EngineInfo,
    ExtractResult,
    ProgressFn,
    StegoEngine,
)
from .hstego_engine import HStegoEngine

DEFAULT_ENGINE = "hstego"

_ENGINES: dict[str, StegoEngine] = {}
_LOCK = threading.RLock()


class GenerativeEngineStub(StegoEngine):
    """生成式（无载体）隐写引擎占位。

    课题第二阶段（AIGC 生成式信息隐藏）在这里接入：模型现生成载体，
    把秘密藏进图像生成过程本身（如扩散模型的初始噪声/采样轨迹）。
    接口与 HStegoEngine 完全一致，所以上层 API 与前端不需要改动。
    """

    name = "diffusion"
    display_name = "生成式隐写（占位）"

    def info(self) -> EngineInfo:
        return EngineInfo(
            name=self.name,
            display_name=self.display_name,
            available=False,
            kind="generative",
            domains=["latent"],
            algorithms=[],
            notes=(
                "课题第二阶段的接入位：无载体/生成式隐写（扩散模型采样轨迹中承载消息）。"
                "接口已与 HStegoEngine 对齐，实现后上层无需改动。"
            ),
            unavailable_reason="尚未实现（Phase 2）",
        )

    def _unavailable(self) -> None:
        raise EngineUnavailableError(
            "生成式隐写引擎尚未实现（Phase 2）",
            detail={"engine": self.name},
        )

    def capacity(
        self, cover_path: str | Path, payload_path: str | Path | None = None
    ) -> CapacityReport:
        self._unavailable()

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
        self._unavailable()

    def extract(
        self,
        stego_path: str | Path,
        key: str,
        out_path: str | Path,
        *,
        progress: ProgressFn | None = None,
        text_preview_chars: int = 2000,
    ) -> ExtractResult:
        self._unavailable()


def register_engine(engine: StegoEngine) -> None:
    with _LOCK:
        _ENGINES[engine.name] = engine


def init_registry(settings: Settings) -> None:
    """按配置构造引擎。幂等。"""

    if DEFAULT_ENGINE not in _ENGINES:
        register_engine(
            HStegoEngine(
                settings.project_root,
                {
                    "jpeg_retry_qualities": settings.jpeg_retry_qualities,
                    "jpeg_subsampling": settings.jpeg_subsampling,
                    "max_embed_attempts": settings.max_embed_attempts,
                    "max_upload_bytes": settings.max_upload_bytes,
                    "max_payload_bytes": settings.max_payload_bytes,
                },
            )
        )
    if "diffusion" not in _ENGINES:
        register_engine(GenerativeEngineStub())


def get_engine(name: str | None = None) -> StegoEngine:
    with _LOCK:
        key = name or DEFAULT_ENGINE
        engine = _ENGINES.get(key)
    if engine is None:
        raise EngineUnavailableError(
            f"未知引擎：{key}",
            detail={"available": sorted(_ENGINES)},
        )
    return engine


def list_engines() -> list[StegoEngine]:
    with _LOCK:
        return list(_ENGINES.values())
