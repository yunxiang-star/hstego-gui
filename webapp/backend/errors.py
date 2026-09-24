"""统一错误码与异常。

错误码对前端友好（可映射文案），不暴露 Python 堆栈。
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """带错误码的业务异常。"""

    code = "internal_error"
    status_code = 500
    message = "内部错误"

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: Any = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class UnsupportedImageError(AppError):
    code = "unsupported_image"
    status_code = 415
    message = "不支持的图像格式（空间域支持 png/pgm/tif，压缩域支持 jpg）"


class ImageTooLargeError(AppError):
    code = "image_too_large"
    status_code = 413
    message = "图像或文件超出体积上限"


class PayloadTooLargeError(AppError):
    code = "payload_too_large"
    status_code = 413
    message = "载荷超出载体容量"


class InvalidImageError(AppError):
    code = "invalid_image"
    status_code = 400
    message = "文件不是可解析的图像"


class MissingParameterError(AppError):
    code = "missing_parameter"
    status_code = 400
    message = "缺少必填参数"


class JobNotFoundError(AppError):
    code = "job_not_found"
    status_code = 404
    message = "作业不存在或已过期"


class ArtifactNotFoundError(AppError):
    code = "artifact_not_found"
    status_code = 404
    message = "产物不存在或已过期"


class EngineUnavailableError(AppError):
    code = "engine_unavailable"
    status_code = 503
    message = "隐写引擎不可用（原生扩展未加载）"


class EngineFailureError(AppError):
    code = "engine_failure"
    status_code = 500
    message = "引擎执行失败"
