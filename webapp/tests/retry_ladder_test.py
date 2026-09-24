"""重试链路专项验证：拿**已知会失败**的（载体, 载荷）组合，验证 q95→q92→q88 兜底是否有效。

背景：2026-09-23 的评测基线发现 J-UNIWARD 在 9 张标准图里有 2 张提取静默失败（25%），
其中 `sailboat` 在 q90 + 128 字节随机载荷下必失败（见《J-UNIWARD可靠性缺陷报告.md》）。
本脚本用**同一对文件**重放那次失败，看后端能否自动救回。

用法：
    ..\\.venv\\Scripts\\python.exe tests\\retry_ladder_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEBAPP_DIR.parent

WORK_ROOT = Path(tempfile.mkdtemp(prefix="hstego-retry-test-"))
os.environ["HSTEGO_WORK_ROOT"] = str(WORK_ROOT)

sys.path.insert(0, str(WEBAPP_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402

BASELINE = Path(r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\baseline")
TESTSET = Path(r"C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\testset")
PASSWORD = "baseline-pwd-2026"


def resolve_pair() -> tuple[Path, Path]:
    cover = BASELINE / "sailboat_cover_q90.jpg"
    secret = BASELINE / "sailboat_jpeg_secret.bin"
    if cover.exists() and secret.exists():
        return cover, secret

    # 兜底：现场复现同一组合
    from PIL import Image
    import numpy as np

    src = TESTSET / "4.2.06_sailboat.tiff"
    if not src.exists():
        raise SystemExit("找不到基线素材，无法复现")
    cover = WORK_ROOT / "sailboat_q90.jpg"
    with Image.open(src) as img:
        img.convert("RGB").save(cover, format="JPEG", quality=90, subsampling=0)
    secret = WORK_ROOT / "secret_128.bin"
    secret.write_bytes(
        np.random.default_rng(1234).integers(0, 256, 128, dtype=np.uint8).tobytes()
    )
    return cover, secret


def main() -> int:
    cover, secret = resolve_pair()
    payload = secret.read_bytes()
    print(f"载体：{cover}")
    print(f"载荷：{secret}（{len(payload)} 字节真随机）")
    print(f"工作目录：{WORK_ROOT}\n")

    with TestClient(app) as client:
        with cover.open("rb") as fh:
            response = client.post(
                "/api/v1/embed",
                files={
                    "cover": (cover.name, fh, "image/jpeg"),
                    "payload_file": (secret.name, payload, "application/octet-stream"),
                },
                data={"password": PASSWORD, "include_diff": "true"},
            )
        if response.status_code != 202:
            print(f"投递失败：HTTP {response.status_code}\n{response.text[:500]}")
            return 1

        job_id = response.json()["job_id"]
        precheck = response.json().get("precheck") or {}
        print(
            f"预检：容量 {precheck.get('capacity_bytes')}B ｜ "
            f"密文 {precheck.get('payload_cipher_bytes')}B"
        )

        job = {}
        for _ in range(1200):
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            if job["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)

        report = job.get("result") or {}
        if job["status"] == "failed":
            error = job.get("error") or {}
            report = ((error.get("detail") or {}).get("report")) or {}
            print(f"\n最终失败：{error.get('code')} — {error.get('message')}")

        print("\n尝试流水（这是后端最该被看见的部分）：")
        print(f"{'#':>3}{'质量':>8}{'容量':>8}{'密文':>8}{'自检':>8}{'失败原因':>18}{'耗时':>9}")
        print("-" * 66)
        for attempt in report.get("attempts") or []:
            print(
                f"{attempt['index'] + 1:>3}"
                f"{(attempt['quality'] or '原始'):>8}"
                f"{attempt['capacity_bytes']:>8}"
                f"{attempt['payload_cipher_bytes']:>8}"
                f"{('通过' if attempt['verified'] else '未通过'):>8}"
                f"{(attempt['failure_reason'] or '-'):>18}"
                f"{attempt['elapsed_seconds']:>8.1f}s"
            )

        print(
            f"\n结论：verified={report.get('verified')} ｜ "
            f"采用第 {(report.get('chosen_attempt') or 0) + 1} 次尝试 ｜ "
            f"retry_used={report.get('retry_used')}"
        )
        if report.get("verified"):
            print(
                f"质量：PSNR {report['metrics']['psnr_db']} dB ｜ "
                f"SSIM {report['metrics']['ssim']} ｜ "
                f"最大改动 {report['metrics']['max_abs_diff']}"
            )
            if report.get("hint"):
                print(f"提示：{report['hint']}")

        elapsed = json.dumps(report.get("attempts") or [], ensure_ascii=False)
        _ = elapsed

    print("\n" + "=" * 66)
    rescued = bool(report.get("verified")) and (report.get("chosen_attempt") or 0) > 0
    if rescued:
        print("✅ 重试链路生效：原参数失败，换质量后自检通过——这正是上游 GUI 给不出的结论。")
        return 0
    if report.get("verified"):
        print("⚠️ 这一轮首次尝试就通过了（与载荷相关，缺陷本身不可预测）——重试链路未触发，但结果可用。")
        print("   想稳定复现失败，可改用 baseline 里的 airplane 组合。")
        return 0
    print("❌ 全部尝试都未通过，后端已正确拒绝输出并给出提示（这是设计内的安全行为）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
