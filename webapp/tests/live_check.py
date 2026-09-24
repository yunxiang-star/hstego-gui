"""对**真实运行中的服务**做一次端到端检查（含 SSE 流式进度）。

冒烟测试用的是进程内 TestClient；这个脚本走真 HTTP，用来验证
uvicorn、SSE、以及文本载荷的往返。

用法：
    :: 另开一个窗口
    run-server.bat
    :: 然后
    ..\\.venv\\Scripts\\python.exe tests\\live_check.py [--base-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

WEBAPP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEBAPP_DIR.parent

SECRET_TEXT = "隐写测试：如果你看到这句话，说明 UNIWARD + STC 的往返在真实 HTTP 链路上是通的。—— ILLENIUM 2026-09-23"
PASSWORD = "demo-P4ssw0rd"


def pick_cover() -> Path:
    for candidate in (
        PROJECT_ROOT / "testing" / "cover.png",
        PROJECT_ROOT / "testing" / "cover_color.png",
    ):
        if candidate.exists():
            return candidate
    raise SystemExit("找不到测试载体（testing/cover.png）")


def stream_events(base: str, job_id: str, timeout: float = 600.0) -> dict:
    """跟一遍 SSE，打印阶段变化，返回最终快照。"""

    final: dict = {}
    deadline = time.time() + timeout
    with httpx.stream(
        "GET", f"{base}/api/v1/jobs/{job_id}/events", timeout=timeout
    ) as response:
        response.raise_for_status()
        event = None
        for line in response.iter_lines():
            if time.time() > deadline:
                break
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
                if event == "progress":
                    print(
                        f"   [SSE] {payload.get('stage'):>9} "
                        f"{payload.get('progress'):>5} — {payload.get('message')}"
                    )
                elif event == "done":
                    final = payload
                    print(f"   [SSE] 作业结束：{payload.get('status')}")
                    break
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    ok = True
    with httpx.Client(timeout=120.0) as client:
        print(f"目标服务：{base}")
        health = client.get(f"{base}/api/v1/health")
        health.raise_for_status()
        info = health.json()
        print(f"health：{json.dumps(info, ensure_ascii=False)}")
        if not info["engine_available"]:
            print("引擎不可用，后续检查无意义")
            return 1

        cover = pick_cover()
        print(f"载体：{cover}")

        with cover.open("rb") as fh:
            response = client.post(
                f"{base}/api/v1/embed",
                files={"cover": (cover.name, fh, "image/png")},
                data={"password": PASSWORD, "payload_text": SECRET_TEXT},
            )
        if response.status_code != 202:
            print(f"投递失败：HTTP {response.status_code} {response.text[:400]}")
            return 1
        submit = response.json()
        print(
            f"已投递作业 {submit['job_id']}｜预检容量 "
            f"{(submit.get('precheck') or {}).get('capacity_bytes')}B"
        )

        final = stream_events(base, submit["job_id"])
        report = final.get("result") or {}
        if final.get("status") != "succeeded":
            print(f"嵌入失败：{final.get('error')}")
            return 1

        print(
            f"嵌入结论：verified={report['verified']}｜{report['domain']}/{report['algorithm']}｜"
            f"尝试 {len(report['attempts'])} 次｜重试={report.get('retry_used')}"
        )
        metrics = report.get("metrics") or {}
        print(
            f"质量：PSNR {metrics.get('psnr_db')} dB｜SSIM {metrics.get('ssim')}｜"
            f"改动比例 {metrics.get('changed_ratio')}"
        )
        for artifact in report.get("artifacts", []):
            print(
                f"  产物 {artifact['kind']:<8} {artifact['size']:>8}B "
                f"{artifact['filename']} → {artifact['url']}"
            )

        stego_art = next(
            (a for a in report["artifacts"] if a["kind"] == "stego"), None
        )
        diff_art = next((a for a in report["artifacts"] if a["kind"] == "diff"), None)
        if stego_art is None:
            print("没有 stego 产物")
            return 1

        stego_bytes = client.get(f"{base}{stego_art['url']}").content
        if len(stego_bytes) != stego_art["size"]:
            print("下载体积与登记不符")
            ok = False

        if diff_art is not None:
            preview = client.get(f"{base}{diff_art['preview_url']}?max_side=512")
            print(
                f"差分图预览：HTTP {preview.status_code}"
                f"（{len(preview.content)}B, {preview.headers.get('content-type')}）"
            )
            ok = ok and preview.status_code == 200

        # 反向提取
        response = client.post(
            f"{base}/api/v1/extract",
            files={"stego": (stego_art["filename"], stego_bytes)},
            data={"password": PASSWORD},
        )
        extract_job = stream_events(base, response.json()["job_id"])
        extract_result = extract_job.get("result") or {}
        text = extract_result.get("text")
        match = text == SECRET_TEXT
        print(
            f"\n提取结论：is_text={extract_result.get('is_text')}｜"
            f"sha256={extract_result.get('payload_sha256')}"
            f"｜与原文一致={match}"
        )
        print(f"提取内容：{text!r}")
        ok = ok and match

        expected_sha = hashlib.sha256(SECRET_TEXT.encode("utf-8")).hexdigest()
        ok = ok and extract_result.get("payload_sha256") == expected_sha

        # 错误口令
        response = client.post(
            f"{base}/api/v1/extract",
            files={"stego": ("stego.png", stego_bytes)},
            data={"password": "wrong-password"},
        )
        wrong_id = response.json()["job_id"]
        wrong = client.get(f"{base}/api/v1/jobs/{wrong_id}").json()
        for _ in range(240):
            if wrong["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)
            wrong = client.get(f"{base}/api/v1/jobs/{wrong_id}").json()
        print(
            f"错误口令：status={wrong['status']}｜code={(wrong.get('error') or {}).get('code')}"
        )
        ok = ok and wrong["status"] == "failed"

    print("\n" + ("=" * 56))
    print("真实链路检查：" + ("全部通过 ✅" if ok else "存在失败项 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
