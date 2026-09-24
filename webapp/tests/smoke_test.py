"""后端冒烟测试：用真实标准图跑一遍 HTTP 全链路。

跑法（不需要 pytest）：
    cd D:\\projects\\hstego\\webapp
    ..\\.venv\\Scripts\\python.exe tests\\smoke_test.py

覆盖：
  1. /health 与原生扩展加载状态
  2. /capacity 的容量口径（密文预算 vs 原始载荷上限）
  3. 空间域（PNG / S-UNIWARD）嵌入 → 自检 → 下载 → 反向提取，比对 sha256
  4. 压缩域（JPEG / J-UNIWARD）同上
  5. 载荷超限 → 413
  6. 错误口令 / 无消息 → 作业失败且错误码为 not_found
  7. （可选 --hard-jpeg）用已知失败载体触发 q95→q92 重试
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEBAPP_DIR.parent

WORK_ROOT = Path(tempfile.mkdtemp(prefix="hstego-webapp-test-"))
os.environ.setdefault("HSTEGO_WORK_ROOT", str(WORK_ROOT))
os.environ.setdefault("HSTEGO_ARTIFACT_TTL", "600")

sys.path.insert(0, str(WEBAPP_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402

BASELINE_DIR = Path(r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\baseline")
TESTSET_DIR = Path(r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\testset")

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, extra: str = "") -> None:
    tag = "PASS" if condition else "FAIL"
    print(f"[{tag}] {name}{(' — ' + extra) if extra else ''}")
    (PASSED if condition else FAILED).append(name)


def wait_job(client: TestClient, job_id: str, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        payload = client.get(f"/api/v1/jobs/{job_id}").json()
        if payload.get("status") != last:
            last = payload.get("status")
            print(
                f"      · {payload.get('status')} {payload.get('stage')} "
                f"{payload.get('progress')} — {payload.get('message')}"
            )
        if payload.get("status") in ("succeeded", "failed"):
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"作业 {job_id} 超时")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_spatial_cover(target: Path) -> Path | None:
    """优先用工程自带的 cover.png，没有就从 SIPI tiff 转一张。"""

    bundled = PROJECT_ROOT / "testing" / "cover.png"
    if bundled.exists():
        shutil.copyfile(bundled, target)
        return target
    source = TESTSET_DIR / "4.2.01_splash.tiff"
    if not source.exists():
        return None
    from PIL import Image

    with Image.open(source) as img:
        img.convert("RGB").save(target, format="PNG")
    return target


def make_jpeg_cover(target: Path) -> Path | None:
    bundled = PROJECT_ROOT / "testing" / "cover.jpg"
    if bundled.exists():
        shutil.copyfile(bundled, target)
        return target
    source = TESTSET_DIR / "4.2.03_baboon.tiff"
    if not source.exists():
        return None
    from PIL import Image

    with Image.open(source) as img:
        img.convert("RGB").save(target, format="JPEG", quality=90, subsampling=0)
    return target


def hard_jpeg_cover(target: Path) -> Path | None:
    """已知会让 J-UNIWARD 提取静默失败的载体（见 J-UNIWARD可靠性缺陷报告）。"""

    source = BASELINE_DIR / "sailboat_cover_q90.jpg"
    if not source.exists():
        source = TESTSET_DIR / "4.2.06_sailboat.tiff"
        if not source.exists():
            return None
        from PIL import Image

        with Image.open(source) as img:
            img.convert("RGB").save(target, format="JPEG", quality=90, subsampling=0)
        return target
    shutil.copyfile(source, target)
    return target


def roundtrip(
    client: TestClient,
    cover: Path,
    payload: bytes,
    label: str,
    expect_verified: bool = True,
) -> dict:
    print(f"\n=== {label} ===")
    with cover.open("rb") as fh:
        response = client.post(
            "/api/v1/embed",
            files={
                "cover": (cover.name, fh, "application/octet-stream"),
                "payload_file": ("secret.bin", payload, "application/octet-stream"),
            },
            data={"password": "Test-P4ssw0rd", "include_diff": "true"},
        )
    if response.status_code != 202:
        check(f"{label} 投递作业", False, f"HTTP {response.status_code} {response.text[:200]}")
        return {}
    check(f"{label} 投递作业", True)

    submit = response.json()
    precheck = submit.get("precheck") or {}
    print(
        f"      容量 {precheck.get('capacity_bytes')}B ｜ "
        f"密文 {precheck.get('payload_cipher_bytes')}B ｜ "
        f"域 {precheck.get('domain')}/{precheck.get('algorithm')}"
    )

    job = wait_job(client, submit["job_id"])
    report = (job.get("result") or {}).get("report") if "report" in (job.get("result") or {}) else job.get("result")
    if job["status"] == "failed":
        error = job.get("error") or {}
        print(f"      失败：{error.get('code')} {error.get('message')}")
        report = ((error.get("detail") or {}).get("report")) or {}
    check(
        f"{label} 作业成功",
        job["status"] == "succeeded" or not expect_verified,
        f"status={job['status']}",
    )
    check(
        f"{label} 自检通过（verified）",
        bool(report.get("verified")) == expect_verified,
        f"verified={report.get('verified')} attempts={len(report.get('attempts') or [])}",
    )
    if not report.get("verified"):
        return report

    metrics = report.get("metrics") or {}
    print(
        f"      PSNR {metrics.get('psnr_db')} dB ｜ SSIM {metrics.get('ssim')} ｜ "
        f"最大改动 {metrics.get('max_abs_diff')} ｜ 改动比例 {metrics.get('changed_ratio')}"
    )
    check(f"{label} 有 PSNR 指标", metrics.get("psnr_db") is not None)

    artifacts = {a["kind"]: a for a in report.get("artifacts") or []}
    check(f"{label} 产出 stego 产物", "stego" in artifacts)
    check(f"{label} 产出差分图", "diff" in artifacts)

    if "stego" not in artifacts:
        return report

    downloaded = client.get(artifacts["stego"]["url"])
    check(f"{label} 下载载密图", downloaded.status_code == 200, f"{len(downloaded.content)}B")

    with cover.open("rb") as fh:
        pass
    response = client.post(
        "/api/v1/extract",
        files={"stego": (artifacts["stego"]["filename"], downloaded.content)},
        data={"password": "Test-P4ssw0rd"},
    )
    check(f"{label} 投递提取作业", response.status_code == 202)
    extract_job = wait_job(client, response.json()["job_id"])
    extract_result = extract_job.get("result") or {}
    check(
        f"{label} 提取成功且 sha256 一致",
        extract_job["status"] == "succeeded"
        and extract_result.get("payload_sha256") == sha256(payload),
        f"sha={extract_result.get('payload_sha256')}",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hard-jpeg",
        action="store_true",
        help="额外跑一例已知失败载体，验证 q95→q92 重试链路（会多花 1–2 分钟）",
    )
    args = parser.parse_args()

    print(f"工作目录：{WORK_ROOT}")
    payload = os.urandom(96)
    payload_sha = sha256(payload)

    with TestClient(app) as client:
        # 1. health
        health = client.get("/api/v1/health").json()
        print(f"\n=== health ===\n{health}")
        check("引擎可用（原生扩展已加载）", health["engine_available"], health.get("engine_import_error") or "")
        check("work_root 可写", health["work_root_writable"])

        engines = client.get("/api/v1/engines").json()
        names = [e["name"] for e in engines["engines"]]
        check("引擎列表含 hstego 与生成式占位", "hstego" in names and "diffusion" in names, str(names))

        # 2. capacity 口径
        spatial_cover = make_spatial_cover(WORK_ROOT / "cover.png")
        if spatial_cover is None:
            print("找不到测试载体，退出")
            return 2

        with spatial_cover.open("rb") as fh:
            cap = client.post(
                "/api/v1/capacity",
                files={"cover": (spatial_cover.name, fh, "image/png")},
            )
        check("容量接口 200", cap.status_code == 200, cap.text[:200])
        cap_json = cap.json()
        print(f"\n=== capacity ===\n{cap_json}")
        check(
            "容量口径：原始上限 = 密文预算 - 60",
            cap_json["max_incompressible_payload_bytes"]
            == max(0, cap_json["capacity_bytes"] - cap_json["cipher_overhead_bytes"]),
        )

        # 3. 空间域往返
        roundtrip(client, spatial_cover, payload, "空间域 PNG")

        # 4. 压缩域往返
        jpeg_cover = make_jpeg_cover(WORK_ROOT / "cover.jpg")
        if jpeg_cover:
            roundtrip(client, jpeg_cover, payload, "压缩域 JPEG")

        # 5. 载荷超限
        tiny = WORK_ROOT / "tiny.png"
        from PIL import Image
        import numpy as np

        Image.fromarray(
            np.full((64, 64, 3), 128, dtype=np.uint8)
        ).save(tiny)
        with tiny.open("rb") as fh:
            over = client.post(
                "/api/v1/embed",
                files={
                    "cover": ("tiny.png", fh, "image/png"),
                    "payload_file": ("big.bin", os.urandom(5000), "application/octet-stream"),
                },
                data={"password": "x"},
            )
        check(
            "载荷超限 → 413 payload_too_large 且预检发生在投递前",
            over.status_code == 413 and over.json().get("code") == "payload_too_large",
            over.text[:200],
        )

        # 6. 错误口令 / 干净图
        response = client.post(
            "/api/v1/extract",
            files={"stego": ("clean.jpg", jpeg_cover.read_bytes())},
            data={"password": "definitely-wrong"},
        )
        wrong_job = wait_job(client, response.json()["job_id"])
        check(
            "干净图/错口令 → not_found（文案三者并列，不断言口令错误）",
            wrong_job["status"] == "failed"
            and (wrong_job.get("error") or {}).get("code") == "not_found",
            str(wrong_job.get("error", {}).get("message"))[:120],
        )

        # 8. 可选：已知失败载体重试链路
        if args.hard_jpeg:
            hard = hard_jpeg_cover(WORK_ROOT / "hard.jpg")
            if hard is not None:
                report = roundtrip(client, hard, os.urandom(32), "压缩域 已知失败载体", expect_verified=True)
                attempts = report.get("attempts") or []
                check(
                    "失败载体被重试链路救回（或按失败正确报错）",
                    bool(report.get("verified")) or len(attempts) > 1,
                    f"attempts={[a.get('quality') for a in attempts]}",
                )

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for name in FAILED:
        print(f"  ✗ {name}")
    print(f"工作目录未清理（可自行查看）：{WORK_ROOT}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
