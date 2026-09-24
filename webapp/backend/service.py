"""业务编排层：把上传件、引擎调用、产物登记串起来。

放在单独模块是为了让 `app.py` 只管 HTTP，让 `engine/` 只管算法，
将来换前端 / 加 CLI 都能复用这一层。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .engine import EmbedResult, ExtractResult, StegoEngine
from .jobs import Job
from .storage import ArtifactStore, is_image_suffix, sanitize_filename


def _stem(path: Path) -> str:
    """（保留给需要从磁盘路径取名的场合）"""

    return path.stem or "image"


def run_embed(
    job: Job,
    *,
    engine: StegoEngine,
    store: ArtifactStore,
    cover_path: Path,
    cover_display_name: str,
    payload_path: Path,
    payload_display_name: str,
    password: str,
    include_diff: bool = True,
    diff_gain: int = 20,
) -> None:
    job_dir = store.job_dir(job.id)
    out_path = job_dir / "stego"
    diff_path = job_dir / "diff.png"

    def progress(stage: str, value: float, message: str) -> None:
        job.set_progress(stage, value, message)

    job.log(f"引擎 {engine.name}｜载体 {cover_display_name}｜载荷 {payload_display_name}")

    result: EmbedResult = engine.embed(
        cover_path,
        payload_path,
        password,
        out_path,
        options={
            "include_diff": include_diff,
            "diff_gain": diff_gain,
            "diff_path": str(diff_path),
        },
        progress=progress,
    )

    report = result.to_dict()

    if not result.ok or not result.verified or result.stego_path is None:
        job.log("嵌入未通过自检，放弃输出", level="error")
        for attempt in result.attempts:
            job.log(
                f"尝试 {attempt.index + 1}"
                f"（{'原始载体' if attempt.quality is None else f'q{attempt.quality}'}）"
                f" → {'通过' if attempt.verified else attempt.failure_reason or '失败'}"
                f"（{attempt.elapsed_seconds:.1f}s）",
                level="warn" if not attempt.verified else "info",
            )
        job.fail(
            {
                "code": "verification_failed",
                "message": result.message,
                "detail": {"report": report, "hint": result.hint},
            }
        )
        return

    artifacts: list[dict[str, Any]] = []
    cover_art = store.register(
        job.id,
        "cover",
        cover_path,
        filename=cover_display_name,
    )
    artifacts.append(cover_art.to_dict())

    payload_art = store.register(
        job.id,
        "payload",
        payload_path,
        filename=payload_display_name,
    )
    artifacts.append(payload_art.to_dict())

    stego_path = Path(result.stego_path)
    stego_name = f"{_stem(cover_path)}_stego{stego_path.suffix}"
    stego_art = store.register(job.id, "stego", stego_path, filename=stego_name)
    artifacts.append(stego_art.to_dict())

    if result.diff_path and Path(result.diff_path).exists():
        diff_art = store.register(
            job.id,
            "diff",
            Path(result.diff_path),
            filename=f"{_stem(cover_path)}_diff_x{diff_gain}.png",
            media_type="image/png",
        )
        artifacts.append(diff_art.to_dict())

    report["artifacts"] = artifacts
    report["retry_used"] = len(result.attempts) > 1

    journal = [
        {
            "index": a.index,
            "quality": a.quality,
            "capacity_bytes": a.capacity_bytes,
            "payload_cipher_bytes": a.payload_cipher_bytes,
            "verified": a.verified,
            "failure_reason": a.failure_reason,
            "elapsed_seconds": round(a.elapsed_seconds, 3),
        }
        for a in result.attempts
    ]
    report["attempt_journal"] = journal

    job.succeed(report, message=result.message)


def run_extract(
    job: Job,
    *,
    engine: StegoEngine,
    store: ArtifactStore,
    stego_path: Path,
    stego_display_name: str,
    password: str,
    text_preview_chars: int = 2000,
) -> None:
    job_dir = store.job_dir(job.id)
    out_path = job_dir / "extracted.bin"

    def progress(stage: str, value: float, message: str) -> None:
        job.set_progress(stage, value, message)

    job.log(f"引擎 {engine.name}｜载密图 {stego_display_name}")

    result: ExtractResult = engine.extract(
        stego_path,
        password,
        out_path,
        progress=progress,
        text_preview_chars=text_preview_chars,
    )

    report = result.to_dict()
    stego_art = store.register(
        job.id, "stego", stego_path, filename=stego_display_name
    )
    report["artifacts"] = [stego_art.to_dict()]

    if not result.ok:
        job.log(result.message, level="warn")
        job.fail(
            {
                "code": result.reason,
                "message": result.message,
                "detail": report,
            }
        )
        return

    download_name = "extracted.txt" if result.is_text else "extracted.bin"
    payload_path = Path(result.payload_path) if result.payload_path else out_path
    extracted_art = store.register_bytes(
        job.id,
        "extracted",
        download_name,
        payload_path.read_bytes(),
    )
    report["artifacts"].append(extracted_art.to_dict())
    report["download_name"] = download_name

    size = result.payload_bytes
    job.succeed(report, message=f"提取成功，共 {size} 字节")


def capacity_for_upload(
    *,
    engine: StegoEngine,
    cover_path: Path,
    payload_path: Path | None = None,
) -> dict[str, Any]:
    """同步容量预估。给前端做"超限拦截"用。

    调用方负责清理临时目录。
    """

    report = engine.capacity(cover_path, payload_path)
    payload = report.to_dict()
    if payload_path is not None:
        payload["payload_filename"] = sanitize_filename(payload_path.name)
    return payload


def payload_kind(filename: str, is_image: bool = False) -> str:
    if is_image:
        return "image"
    return "text" if filename.lower().endswith((".txt", ".md", ".json", ".csv")) else "file"


def describe_payload(path: Path) -> dict[str, Any]:
    return {
        "filename": sanitize_filename(path.name),
        "size": path.stat().st_size,
        "kind": payload_kind(path.name, is_image=is_image_suffix(path)),
    }
