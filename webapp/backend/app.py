"""FastAPI 应用：路由层。

只做三件事——校验请求、投递作业、返回产物。算法在 `engine/`，编排在 `service.py`。

端点一览
    GET  /                                      面向普通用户的图形界面（backend/web/）
    GET  /ui/app.js  /ui/styles.css             界面静态资源
    GET  /docs                                  开发者接口文档（Swagger）
    GET  /api/v1/health                         健康检查（含原生扩展加载状态）
    GET  /api/v1/engines                        可用引擎（含 AIGC 引擎占位）
    POST /api/v1/capacity                       容量预估（同步，前端超限拦截用）
    POST /api/v1/embed                          投递嵌入作业 → 202 + job_id
    POST /api/v1/extract                        投递提取作业 → 202 + job_id
    GET  /api/v1/jobs                           最近作业列表
    GET  /api/v1/jobs/{job_id}                  作业状态
    GET  /api/v1/jobs/{job_id}/events           作业进度 SSE
    GET  /api/v1/artifacts/{token}              下载产物（?inline=1 为内联）
    GET  /api/v1/artifacts/{token}/preview      图像产物预览（?max_side=1600）
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from PIL import Image

from . import __version__
from .config import Settings, get_settings
from .engine import get_engine, init_registry, list_engines
from .errors import (
    AppError,
    ArtifactNotFoundError,
    ImageTooLargeError,
    InvalidImageError,
    JobNotFoundError,
    MissingParameterError,
    PayloadTooLargeError,
)
from .jobs import JobManager
from .schemas import (
    CapacityResponse,
    EnginesResponse,
    ErrorResponse,
    HealthResponse,
    JobResponse,
    JobSubmitResponse,
)
from .service import capacity_for_upload, run_embed, run_extract
from .storage import ArtifactStore, is_image_suffix, sanitize_filename

API_PREFIX = "/api/v1"
PREVIEW_MAX_SIDE = 1600
READ_CHUNK = 512 * 1024

# 面向普通用户的图形界面（纯静态，无构建步骤）。开发者接口仍是 /docs。
UI_DIR = Path(__file__).resolve().parent / "web"
UI_ASSETS = {
    "/ui/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/ui/styles.css": ("styles.css", "text/css; charset=utf-8"),
}

state: dict[str, Any] = {}


# --------------------------------------------------------------------- 启动/关闭


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.work_root.mkdir(parents=True, exist_ok=True)

    init_registry(settings)
    store = ArtifactStore(
        settings.work_root,
        ttl_seconds=settings.artifact_ttl_seconds,
    )
    manager = JobManager(max_workers=2, history_limit=200)
    state.update({"settings": settings, "store": store, "manager": manager})

    app = FastAPI(
        title="HStego Web API",
        version=__version__,
        description=(
            "基于 hstego（UNIWARD + STC）的图像隐写嵌入/提取后端。\n\n"
            "核心差异：**嵌入后往返自检**（`verified`）与**失败自动重试**"
            "——因为上游 JPEG 域存在静默提取失败（实测约 25%），"
            "官方 `extract()` 失败时不抛异常、只写 0 字节文件。\n\n"
            "合规声明：本接口仅用于学术研究与教学演示，不得用于任何非法目的。"
        ),
        docs_url="/docs",
        openapi_tags=[
            {"name": "meta", "description": "健康检查与引擎列表"},
            {"name": "stego", "description": "容量、嵌入、提取"},
            {"name": "jobs", "description": "异步作业状态与进度"},
            {"name": "artifacts", "description": "产物下载与预览"},
        ],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.on_event("startup")
    async def _startup() -> None:
        thread = threading.Thread(
            target=_purge_loop, args=(store,), name="artifact-purge", daemon=True
        )
        thread.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        manager.shutdown(wait=False)

    app.include_router(_build_router(), prefix=API_PREFIX)

    # ------------------------------------------------------------- 图形界面
    # 默认入口给普通用户：一个傻瓜式的单页界面。开发者接口仍然保留在 /docs，
    # 但不再作为根路径的重定向目标——Swagger 的 JSON 请求/响应会把非技术用户劝退。

    @app.get("/", include_in_schema=False)
    async def _root() -> FileResponse:
        return FileResponse(UI_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/favicon.ico", include_in_schema=False)
    async def _favicon() -> Response:
        return Response(status_code=204)

    @app.get("/ui/{asset}", include_in_schema=False)
    async def _ui_asset(asset: str) -> FileResponse:
        entry = UI_ASSETS.get(f"/ui/{asset}")
        if entry is None:
            raise ArtifactNotFoundError("界面资源不存在", detail={"asset": asset})
        filename, media_type = entry
        return FileResponse(UI_DIR / filename, media_type=media_type)

    return app


def _purge_loop(store: ArtifactStore, interval: float = 600.0) -> None:
    while True:
        time.sleep(interval)
        with contextlib.suppress(Exception):
            store.purge_expired()


# --------------------------------------------------------------------- 工具


async def _read_upload(upload: UploadFile, limit: int, field: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ImageTooLargeError(
                f"{field} 超出体积上限（{total} > {limit} 字节）",
                detail={"field": field, "limit": limit},
            )
        chunks.append(chunk)
    with contextlib.suppress(Exception):
        await upload.close()
    if not chunks:
        raise MissingParameterError(f"{field} 为空文件")
    return b"".join(chunks)


def _save_bytes(target_dir: Path, filename: str, data: bytes) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    path.write_bytes(data)
    return path


def _job_urls(job_id: str) -> tuple[str, str]:
    return (
        f"{API_PREFIX}/jobs/{job_id}",
        f"{API_PREFIX}/jobs/{job_id}/events",
    )


def _resolve_manager() -> JobManager:
    return state["manager"]


def _resolve_store() -> ArtifactStore:
    return state["store"]


def _resolve_settings() -> Settings:
    return state["settings"]


# --------------------------------------------------------------------- 路由


def _build_router() -> APIRouter:
    router = APIRouter()

    # ---------------------------------------------------------------- meta

    @router.get(
        "/health",
        response_model=HealthResponse,
        tags=["meta"],
        summary="健康检查",
    )
    async def health() -> dict[str, Any]:
        settings = _resolve_settings()
        engine = get_engine()
        writable = True
        try:
            probe = settings.work_root / ".health"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError:
            writable = False

        info = engine.info()
        hstegolib = getattr(engine, "_hstegolib", None)
        return {
            "status": "ok" if info.available else "degraded",
            "version": __version__,
            "engine_available": info.available,
            "engine_import_error": getattr(engine, "_import_error", None),
            "max_payload_ratio": getattr(hstegolib, "MAX_PAYLOAD", None),
            "project_root": str(settings.project_root),
            "work_root": str(settings.work_root),
            "work_root_writable": writable,
            "jpeg_retry_qualities": list(settings.jpeg_retry_qualities),
        }

    @router.get(
        "/engines",
        response_model=EnginesResponse,
        tags=["meta"],
        summary="可用引擎",
    )
    async def engines() -> dict[str, Any]:
        return {
            "default": "hstego",
            "engines": [engine.info().to_dict() for engine in list_engines()],
        }

    # ---------------------------------------------------------------- stego

    @router.post(
        "/capacity",
        response_model=CapacityResponse,
        response_model_exclude_none=True,
        tags=["stego"],
        summary="容量预估（同步）",
        responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
    )
    async def capacity(
        cover: UploadFile = File(..., description="载体图（png/jpg/tif/pgm）"),
        payload_file: UploadFile | None = File(None, description="可选：待藏文件"),
        payload_text: str | None = Form(None, description="可选：待藏文本"),
        engine_name: str = Form("hstego"),
    ) -> dict[str, Any]:
        settings = _resolve_settings()
        store = _resolve_store()
        engine = get_engine(engine_name)

        tmp_dir = store.temp_dir()
        try:
            cover_bytes = await _read_upload(
                cover, settings.max_upload_bytes, "载体图"
            )
            cover_path = _save_bytes(
                tmp_dir,
                f"input_{sanitize_filename(cover.filename or 'cover.png')}",
                cover_bytes,
            )
            engine.detect_domain(cover_path)  # 不支持的格式在这里就抛 AppError

            payload_path: Path | None = None
            if payload_file is not None and payload_file.filename:
                payload_bytes = await _read_upload(
                    payload_file, settings.max_payload_bytes, "载荷文件"
                )
                payload_path = _save_bytes(
                    tmp_dir,
                    f"payload_{sanitize_filename(payload_file.filename)}",
                    payload_bytes,
                )
            elif payload_text is not None and payload_text != "":
                payload_path = _save_bytes(
                    tmp_dir, "payload_message.txt", payload_text.encode("utf-8")
                )

            return capacity_for_upload(
                engine=engine, cover_path=cover_path, payload_path=payload_path
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @router.post(
        "/embed",
        status_code=202,
        response_model=JobSubmitResponse,
        tags=["stego"],
        summary="投递嵌入作业",
        responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
    )
    async def embed(
        cover: UploadFile = File(..., description="载体图"),
        password: str = Form(..., description="口令（决定嵌入位置与加密密钥）"),
        payload_file: UploadFile | None = File(None, description="待藏文件"),
        payload_text: str | None = Form(None, description="待藏文本"),
        engine_name: str = Form("hstego"),
        include_diff: bool = Form(True, description="是否生成差分放大图"),
        diff_gain: int = Form(20, description="差分放大倍数"),
        precheck: bool = Form(True, description="是否先做容量预检，超限立刻 413"),
    ) -> dict[str, Any]:
        settings = _resolve_settings()
        store = _resolve_store()
        manager = _resolve_manager()
        engine = get_engine(engine_name)

        if not password:
            raise MissingParameterError("口令不能为空")

        if (payload_file is None or not payload_file.filename) and not payload_text:
            raise MissingParameterError("必须提供 payload_file 或 payload_text 之一")

        job_id = uuid.uuid4().hex[:16]
        job_dir = store.job_dir(job_id)

        cover_bytes = await _read_upload(cover, settings.max_upload_bytes, "载体图")
        cover_name = sanitize_filename(cover.filename or "cover.png")
        cover_path = _save_bytes(job_dir, f"input_{cover_name}", cover_bytes)

        try:
            engine.detect_domain(cover_path)
        except AppError:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

        if payload_file is not None and payload_file.filename:
            payload_bytes = await _read_upload(
                payload_file, settings.max_payload_bytes, "载荷文件"
            )
            payload_name = sanitize_filename(payload_file.filename)
        else:
            payload_bytes = (payload_text or "").encode("utf-8")
            payload_name = "message.txt"
            if len(payload_bytes) > settings.max_payload_bytes:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise ImageTooLargeError("载荷文本超出体积上限")

        payload_path = _save_bytes(job_dir, f"payload_{payload_name}", payload_bytes)

        precheck_info: dict[str, Any] | None = None
        if precheck:
            try:
                precheck_info = capacity_for_upload(
                    engine=engine, cover_path=cover_path, payload_path=payload_path
                )
            except AppError:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise
            if precheck_info.get("fits") is False:
                detail = {
                    "capacity_bytes": precheck_info["capacity_bytes"],
                    "payload_cipher_bytes": precheck_info["payload_cipher_bytes"],
                    "payload_bytes": precheck_info["payload_bytes"],
                    "max_incompressible_payload_bytes": precheck_info[
                        "max_incompressible_payload_bytes"
                    ],
                    "domain": precheck_info["domain"],
                }
                shutil.rmtree(job_dir, ignore_errors=True)
                raise PayloadTooLargeError(
                    f"载荷超出载体容量：密文需要 {detail['payload_cipher_bytes']} 字节，"
                    f"该载体只能容纳 {detail['capacity_bytes']} 字节"
                    f"（同类图容量差异可达 3 倍以上，建议换纹理更丰富的载体）",
                    detail=detail,
                )

        manager.submit(
            "embed",
            functools.partial(
                run_embed,
                engine=engine,
                store=store,
                cover_path=cover_path,
                cover_display_name=cover_name,
                payload_path=payload_path,
                payload_display_name=payload_name,
                password=password,
                include_diff=include_diff,
                diff_gain=diff_gain,
            ),
            label=f"{cover_name} ← {payload_name}",
            job_id=job_id,
        )

        status_url, events_url = _job_urls(job_id)
        return {
            "job_id": job_id,
            "kind": "embed",
            "status": "queued",
            "status_url": status_url,
            "events_url": events_url,
            "precheck": precheck_info,
        }

    @router.post(
        "/extract",
        status_code=202,
        response_model=JobSubmitResponse,
        tags=["stego"],
        summary="投递提取作业",
        responses={400: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
    )
    async def extract(
        stego: UploadFile = File(..., description="载密图"),
        password: str = Form(..., description="口令"),
        engine_name: str = Form("hstego"),
        text_preview_chars: int = Form(2000, description="文本预览截断长度"),
    ) -> dict[str, Any]:
        settings = _resolve_settings()
        store = _resolve_store()
        manager = _resolve_manager()
        engine = get_engine(engine_name)

        if not password:
            raise MissingParameterError("口令不能为空")

        job_id = uuid.uuid4().hex[:16]
        job_dir = store.job_dir(job_id)

        stego_bytes = await _read_upload(stego, settings.max_upload_bytes, "载密图")
        stego_name = sanitize_filename(stego.filename or "stego.png")
        stego_path = _save_bytes(job_dir, f"input_{stego_name}", stego_bytes)

        try:
            engine.detect_domain(stego_path)
        except AppError:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

        manager.submit(
            "extract",
            functools.partial(
                run_extract,
                engine=engine,
                store=store,
                stego_path=stego_path,
                stego_display_name=stego_name,
                password=password,
                text_preview_chars=max(0, min(text_preview_chars, 200_000)),
            ),
            label=stego_name,
            job_id=job_id,
        )

        status_url, events_url = _job_urls(job_id)
        return {
            "job_id": job_id,
            "kind": "extract",
            "status": "queued",
            "status_url": status_url,
            "events_url": events_url,
        }

    # ---------------------------------------------------------------- jobs

    @router.get("/jobs", tags=["jobs"], summary="最近作业列表")
    async def jobs_list(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
        return {"jobs": _resolve_manager().list_recent(limit)}

    @router.get(
        "/jobs/{job_id}",
        response_model=JobResponse,
        tags=["jobs"],
        summary="作业状态",
        responses={404: {"model": ErrorResponse}},
    )
    async def job_status(job_id: str) -> dict[str, Any]:
        job = _resolve_manager().get(job_id)
        if job is None:
            raise JobNotFoundError("作业不存在或已过期", detail={"job_id": job_id})
        return job.snapshot()

    @router.get(
        "/jobs/{job_id}/events",
        tags=["jobs"],
        summary="作业进度（SSE）",
        response_class=StreamingResponse,
    )
    async def job_events(job_id: str, request: Request) -> StreamingResponse:
        job = _resolve_manager().get(job_id)
        if job is None:
            raise JobNotFoundError("作业不存在或已过期", detail={"job_id": job_id})

        async def event_stream() -> AsyncIterator[str]:
            last_seq = -1
            yield _sse("open", {"job_id": job_id, "status": job.status})
            while True:
                if await request.is_disconnected():
                    break
                snapshot = job.snapshot(include_logs=False)
                if snapshot["seq"] != last_seq:
                    last_seq = snapshot["seq"]
                    yield _sse("progress", snapshot)
                if job.finished:
                    yield _sse("done", job.snapshot())
                    break
                changed = await asyncio.to_thread(job.wait_for_update, last_seq, 15.0)
                if not changed:
                    yield ": keepalive\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ---------------------------------------------------------- artifacts

    @router.get(
        "/artifacts/{token}",
        tags=["artifacts"],
        summary="下载产物",
        responses={404: {"model": ErrorResponse}},
    )
    async def download_artifact(
        token: str,
        inline: bool = Query(False, description="为 1 时浏览器内联展示"),
    ) -> FileResponse:
        artifact = _resolve_store().get(token)
        return FileResponse(
            artifact.path,
            media_type=artifact.media_type,
            filename=artifact.filename,
            content_disposition_type="inline" if inline else "attachment",
        )

    @router.get(
        "/artifacts/{token}/preview",
        tags=["artifacts"],
        summary="图像产物预览",
        responses={404: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
    )
    async def preview_artifact(
        token: str,
        max_side: int = Query(PREVIEW_MAX_SIDE, ge=64, le=4096),
    ) -> FileResponse:
        artifact = _resolve_store().get(token)
        if not is_image_suffix(artifact.path) and not artifact.media_type.startswith(
            "image/"
        ):
            raise InvalidImageError(
                "该产物不是图像，无预览", detail={"kind": artifact.kind}
            )
        preview = _make_preview(artifact.path, max_side)
        return FileResponse(
            preview,
            media_type="image/png",
            filename=f"preview_{artifact.filename}.png",
            content_disposition_type="inline",
        )

    return router


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _make_preview(path: Path, max_side: int) -> Path:
    target = path.with_name(f"{path.stem}.preview{max_side}.png")
    if target.exists() and target.stat().st_mtime >= path.stat().st_mtime:
        return target

    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        img.save(target, format="PNG", optimize=True)
    return target


app = create_app()
