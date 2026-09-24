"""HTTP 契约（Pydantic 模型）。

只对"契约稳定、前端强依赖"的端点建模型；嵌入/提取的详细报告保留为开放字典，
因为它们承载引擎的实现细节（attempts、metrics），字段会随实验推进而增加。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Flexible(BaseModel):
    model_config = ConfigDict(extra="allow")


class ErrorResponse(BaseModel):
    code: str = Field(description="机器可读错误码")
    message: str = Field(description="面向用户的中文提示")
    detail: Any | None = Field(default=None, description="结构化补充信息")


class HealthResponse(Flexible):
    status: str
    version: str
    engine_available: bool
    engine_import_error: str | None = None
    max_payload_ratio: float | None = None
    project_root: str
    work_root: str
    work_root_writable: bool


class EngineInfoResponse(Flexible):
    name: str
    display_name: str
    available: bool
    kind: str
    domains: list[str]
    algorithms: list[str]
    notes: str = ""
    unavailable_reason: str | None = None


class EnginesResponse(Flexible):
    default: str
    engines: list[EngineInfoResponse]


class CapacityResponse(Flexible):
    engine: str
    domain: str = Field(description="spatial 或 jpeg")
    algorithm: str
    capacity_bytes: int = Field(description="密文预算（hstego 口径）")
    cipher_overhead_bytes: int
    max_incompressible_payload_bytes: int
    payload_bytes: int | None = None
    payload_cipher_bytes: int | None = None
    fits: bool | None = None


class JobSubmitResponse(Flexible):
    job_id: str
    kind: str
    status: str
    status_url: str
    events_url: str
    precheck: dict[str, Any] | None = None


class JobResponse(Flexible):
    job_id: str
    kind: str
    status: str = Field(description="queued / running / succeeded / failed")
    stage: str
    progress: float
    message: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ArtifactResponse(Flexible):
    token: str
    kind: str
    filename: str
    media_type: str
    size: int
    sha256: str
    url: str
    preview_url: str
