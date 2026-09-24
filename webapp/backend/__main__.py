"""启动入口：python -m backend [--host ...] [--port ...] [--reload]"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .config import get_settings


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="python -m backend",
        description="HStego Web 后端（FastAPI + hstego UNIWARD/STC）",
    )
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="开发模式：改代码自动重启")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    if args.reload:
        uvicorn.run(
            "backend.app:app",
            host=args.host,
            port=args.port,
            reload=True,
            log_level=args.log_level,
        )
    else:
        from .app import app

        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
