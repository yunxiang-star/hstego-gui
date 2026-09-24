"""引擎层：抽象接口 + 具体实现 + 注册表。"""

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
from .hstego_engine import HStegoEngine
from .registry import (
    DEFAULT_ENGINE,
    get_engine,
    init_registry,
    list_engines,
    register_engine,
)

__all__ = [
    "CapacityReport",
    "DEFAULT_ENGINE",
    "EmbedAttempt",
    "EmbedResult",
    "EngineInfo",
    "ExtractResult",
    "HStegoEngine",
    "ProgressFn",
    "StegoEngine",
    "get_engine",
    "init_registry",
    "list_engines",
    "register_engine",
    "sha256_bytes",
    "sha256_file",
    "sniff_text",
]
