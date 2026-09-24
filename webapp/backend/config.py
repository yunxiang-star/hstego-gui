"""运行配置。全部可用环境变量覆盖，默认值适配本机工程布局。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _default_project_root() -> Path:
    # webapp/backend/config.py -> backend -> webapp -> <工程根>
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """后端配置。"""

    project_root: Path
    """hstego 工程根（hstegolib.py 所在目录，会被加进 sys.path）。"""

    work_root: Path
    """上传文件、载密图、产物的工作目录。"""

    max_upload_bytes: int
    """单次上传体积上限（字节）。hstegolib 自身限制 100 MB。"""

    max_payload_bytes: int
    """载荷文件体积上限（字节）。"""

    artifact_ttl_seconds: int
    """产物保留时长，超时后被后台清理线程回收。"""

    jpeg_retry_qualities: tuple[int, ...]
    """JPEG 域失败后的重编码质量阶梯（实测 q95 对失败载体有效）。"""

    jpeg_subsampling: int
    """重编码时的色度子采样。0 = 4:4:4（不丢色度，代价是体积大）。"""

    max_embed_attempts: int
    """同一载荷最多尝试几次（含首次）。"""

    cors_origins: tuple[str, ...]
    """允许跨域的来源，供前端 dev server 使用。"""

    host: str
    port: int

    @classmethod
    def load(cls) -> "Settings":
        project_root = Path(
            _env_str("HSTEGO_PROJECT_ROOT", str(_default_project_root()))
        ).resolve()
        work_root = Path(
            _env_str("HSTEGO_WORK_ROOT", str(project_root / "output" / "webapp"))
        ).resolve()
        origins = tuple(
            item.strip()
            for item in _env_str(
                "HSTEGO_CORS_ORIGINS",
                "http://127.0.0.1:5173,http://localhost:5173",
            ).split(",")
            if item.strip()
        )
        qualities = tuple(
            int(item)
            for item in _env_str("HSTEGO_JPEG_RETRY_QUALITIES", "95,92,88").split(",")
            if item.strip()
        )
        return cls(
            project_root=project_root,
            work_root=work_root,
            max_upload_bytes=_env_int("HSTEGO_MAX_UPLOAD_BYTES", 64 * 1024 * 1024),
            max_payload_bytes=_env_int("HSTEGO_MAX_PAYLOAD_BYTES", 8 * 1024 * 1024),
            artifact_ttl_seconds=_env_int("HSTEGO_ARTIFACT_TTL", 6 * 3600),
            jpeg_retry_qualities=qualities or (95, 92, 88),
            jpeg_subsampling=_env_int("HSTEGO_JPEG_SUBSAMPLING", 0),
            max_embed_attempts=_env_int("HSTEGO_MAX_ATTEMPTS", 4),
            cors_origins=origins,
            host=_env_str("HSTEGO_HOST", "127.0.0.1"),
            port=_env_int("HSTEGO_PORT", 8000),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings
