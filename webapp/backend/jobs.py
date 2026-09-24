"""作业系统。

嵌入一张 JPEG 要 5–20 秒，失败重试会拉到 1 分钟以上——直接同步返回会让浏览器/反代超时，
而且实施计划明确要求"重试全程对用户可见"。所以：

    POST /embed  -> 立刻返回 job_id
    GET  /jobs/{id}        轮询状态（stage / progress / logs）
    GET  /jobs/{id}/events SSE 实时推送

作业进度更新用 Condition 通知，SSE 端不轮询、不空转。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

JobTarget = Callable[["Job"], None]

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = {STATUS_SUCCEEDED, STATUS_FAILED}

MAX_LOG_ENTRIES = 200


@dataclass
class Job:
    id: str
    kind: str  # embed | extract
    label: str = ""
    status: str = STATUS_QUEUED
    stage: str = "queued"
    progress: float = 0.0
    message: str = "排队中"
    logs: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_LOG_ENTRIES))
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    seq: int = 0

    def __post_init__(self) -> None:
        self._condition = threading.Condition()
        self._appended: list[dict[str, Any]] = []

    # ------------------------------------------------------------- 状态推进

    def set_progress(self, stage: str, value: float, message: str) -> None:
        """推进阶段。注意：不能叫 progress —— 那样会和同名字段打架。"""

        self._push(
            stage=stage,
            progress=max(0.0, min(1.0, float(value))),
            message=message,
        )

    def log(self, message: str, level: str = "info") -> None:
        entry = {"ts": time.time(), "level": level, "message": message}
        with self._condition:
            self.logs.append(entry)
            self._appended.append(entry)
            self.seq += 1
            self._condition.notify_all()

    def mark_running(self) -> None:
        with self._condition:
            self.status = STATUS_RUNNING
            self.started_at = time.time()
            self.seq += 1
            self._condition.notify_all()

    def succeed(self, result: dict[str, Any], message: str = "完成") -> None:
        with self._condition:
            self.status = STATUS_SUCCEEDED
            self.result = result
            self.message = message
            self.stage = "done"
            self.progress = 1.0
            self.finished_at = time.time()
            self.seq += 1
            self._condition.notify_all()

    def fail(self, error: dict[str, Any], message: str | None = None) -> None:
        with self._condition:
            self.status = STATUS_FAILED
            self.error = error
            self.message = message or error.get("message", "失败")
            self.stage = "failed"
            self.finished_at = time.time()
            self.seq += 1
            self._condition.notify_all()

    def _push(self, stage: str, progress: float, message: str) -> None:
        entry = {
            "ts": time.time(),
            "stage": stage,
            "progress": progress,
            "message": message,
        }
        with self._condition:
            self.stage = stage
            self.progress = progress
            if message:
                self.message = message
            self.logs.append(entry)
            self._appended.append(entry)
            self.seq += 1
            self._condition.notify_all()

    # ------------------------------------------------------------- 读取

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def snapshot(self, include_logs: bool = True) -> dict[str, Any]:
        with self._condition:
            payload: dict[str, Any] = {
                "job_id": self.id,
                "kind": self.kind,
                "label": self.label,
                "status": self.status,
                "stage": self.stage,
                "progress": round(self.progress, 4),
                "message": self.message,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_seconds": round(
                    (self.finished_at or time.time()) - (self.started_at or self.created_at),
                    3,
                ),
                "seq": self.seq,
            }
            if include_logs:
                payload["logs"] = list(self.logs)
            if self.result is not None:
                payload["result"] = self.result
            if self.error is not None:
                payload["error"] = self.error
            return payload

    def drain_new_entries(self) -> list[dict[str, Any]]:
        """SSE 用：取出上次之后新增的进度条目。"""

        with self._condition:
            entries = self._appended
            self._appended = []
            return entries

    def wait_for_update(self, last_seq: int, timeout: float = 15.0) -> None:
        with self._condition:
            if self.seq != last_seq:
                return
            self._condition.wait(timeout=timeout)


class JobManager:
    def __init__(self, max_workers: int = 2, history_limit: int = 200) -> None:
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="stego-job"
        )
        self.history_limit = int(history_limit)
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque()
        self._lock = threading.RLock()
        self._futures: dict[str, Future[Any]] = {}

    def submit(
        self,
        kind: str,
        target: JobTarget,
        *,
        label: str = "",
        job_id: str | None = None,
    ) -> Job:
        job = Job(id=job_id or uuid.uuid4().hex[:16], kind=kind, label=label)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self.history_limit:
                stale = self._order.popleft()
                self._jobs.pop(stale, None)
                self._futures.pop(stale, None)
        job.log(f"作业已创建：{kind} {label}".strip())
        future = self.executor.submit(self._run, job, target)
        with self._lock:
            self._futures[job.id] = future
        return job

    def _run(self, job: Job, target: JobTarget) -> None:
        job.mark_running()
        try:
            target(job)
        except Exception as exc:  # noqa: BLE001 - 兜住任何异常并转成作业错误
            from .errors import AppError

            logger.exception("作业 %s (%s) 执行失败", job.id, job.kind)
            if isinstance(exc, AppError):
                job.fail(exc.to_dict())
            else:
                error: dict[str, Any] = {
                    "code": "internal_error",
                    "message": f"{type(exc).__name__}: {exc}",
                }
                if DEBUG:
                    error["detail"] = {"traceback": traceback.format_exc()}
                job.fail(error)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._order)[-limit:]
            jobs = [self._jobs[i] for i in ids if i in self._jobs]
        return [job.snapshot(include_logs=False) for job in reversed(jobs)]

    def shutdown(self, wait: bool = False) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=True)
