"""产物存储：上传件、载密图、差分图、提取出的载荷。

设计要点：
- 每个作业一个独立目录 `<work_root>/jobs/<job_id>/`，互不干扰；
- 对外只暴露随机 token（`secrets.token_urlsafe`），不暴露磁盘路径；
- 有 TTL，过期由后台线程回收，避免演示机磁盘被吃满。
"""

from __future__ import annotations

import mimetypes
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ArtifactNotFoundError
from .engine.base import sha256_file

# 自己认识的类型优先，不靠系统 mimetypes 猜
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pgm": "image/x-portable-graymap",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".bin": "application/octet-stream",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
}

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".pgm", ".tif", ".tiff", ".bmp"}


def guess_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _MEDIA_TYPES:
        return _MEDIA_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def is_image_suffix(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES


@dataclass
class Artifact:
    token: str
    job_id: str
    kind: str  # cover | stego | diff | payload | extracted
    path: Path
    filename: str
    media_type: str
    size: int
    sha256: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self, url_prefix: str = "/api/v1/artifacts") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "token": self.token,
            "kind": self.kind,
            "filename": self.filename,
            "media_type": self.media_type,
            "size": self.size,
            "sha256": self.sha256,
            "url": f"{url_prefix}/{self.token}",
            "preview_url": f"{url_prefix}/{self.token}/preview",
        }
        if self.media_type.startswith("image/"):
            payload["is_image"] = True
        return payload


class ArtifactStore:
    def __init__(self, root: Path, ttl_seconds: int = 6 * 3600, jobs_limit: int = 200) -> None:
        self.root = Path(root)
        self.jobs_root = self.root / "jobs"
        self.uploads_root = self.root / "uploads"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.uploads_root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = int(ttl_seconds)
        self.jobs_limit = int(jobs_limit)
        self._artifacts: dict[str, Artifact] = {}

    # ------------------------------------------------------------- 路径管理

    def job_dir(self, job_id: str) -> Path:
        path = self.jobs_root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def temp_dir(self) -> Path:
        """给同步接口（如容量预估）用的临时目录。"""

        path = self.uploads_root / secrets.token_hex(12)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_upload(self, job_id: str, filename: str, data: bytes) -> Path:
        """把上传的字节落盘，返回路径。文件名会被消毒。"""

        target_dir = self.job_dir(job_id)
        safe = sanitize_filename(filename or "upload.bin")
        path = target_dir / f"input_{safe}"
        path.write_bytes(data)
        return path

    # --------------------------------------------------------------- 登记

    def register(
        self,
        job_id: str,
        kind: str,
        path: Path,
        *,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> Artifact:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        token = secrets.token_urlsafe(16)
        artifact = Artifact(
            token=token,
            job_id=job_id,
            kind=kind,
            path=path,
            filename=filename or path.name,
            media_type=media_type or guess_media_type(path),
            size=path.stat().st_size,
            sha256=sha256_file(path),
        )
        self._artifacts[token] = artifact
        return artifact

    def register_bytes(
        self,
        job_id: str,
        kind: str,
        filename: str,
        data: bytes,
        media_type: str | None = None,
    ) -> Artifact:
        target = self.job_dir(job_id) / sanitize_filename(filename)
        target.write_bytes(data)
        return self.register(
            job_id, kind, target, filename=filename, media_type=media_type
        )

    def get(self, token: str) -> Artifact:
        artifact = self._artifacts.get(token)
        if artifact is None or not artifact.path.exists():
            raise ArtifactNotFoundError(
                "产物不存在或已被清理", detail={"token": token}
            )
        return artifact

    def list_for_job(self, job_id: str) -> list[Artifact]:
        return [a for a in self._artifacts.values() if a.job_id == job_id]

    # --------------------------------------------------------------- 回收

    def purge_expired(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        deadline = now - self.ttl_seconds
        removed = 0

        for token, artifact in list(self._artifacts.items()):
            if artifact.created_at < deadline:
                self._artifacts.pop(token, None)
                removed += 1

        # 按目录 mtime 清理磁盘
        for job_path in sorted(
            self.jobs_root.iterdir() if self.jobs_root.exists() else [],
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
        ):
            try:
                if not job_path.is_dir():
                    continue
                if job_path.stat().st_mtime < deadline:
                    shutil.rmtree(job_path, ignore_errors=True)
                    removed += 1
            except OSError:
                continue

        # 上传暂存区整体限龄
        for upload in self.uploads_root.glob("*") if self.uploads_root.exists() else []:
            try:
                if upload.is_dir():
                    if upload.stat().st_mtime < deadline:
                        shutil.rmtree(upload, ignore_errors=True)
                        removed += 1
                elif upload.stat().st_mtime < deadline:
                    upload.unlink()
                    removed += 1
            except OSError:
                continue

        return removed


def sanitize_filename(name: str) -> str:
    """只保留安全字符，防路径穿越。"""

    keep = []
    for ch in name.strip().replace("\\", "/").split("/")[-1]:
        if ch.isalnum() or ch in "._- ":
            keep.append(ch)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip(" .") or "file.bin"
    return cleaned[:120]
