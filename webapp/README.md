# HStego Web 后端

> **路径说明**：本文写于原工程 `D:\projects\hstego\`。在本仓库里，
> 本篇所有 `D:\projects\hstego\webapp\` 都对应 **`<仓库根>\webapp\`**，
> 而 `<仓库根>\.venv` 由根目录的 `setup.bat` 自动生成到 `<仓库根>\hstego-runtime\.venv`。
> 最快路径：在仓库根目录双击 `setup.bat`，然后双击 `hstego-runtime\webapp\run-server.bat`。

课题《基于 AIGC 模型的生成式信息隐藏应用程序》的 **Phase 1 · D9–D10** 产物：
把 hstego（UNIWARD + STC）封装成 HTTP 服务，为 Phase 2 的前端单页应用提供接口。

> 上游自带 `hstegogui.py`（Tkinter 向导），所以"做个界面"本身不是创新点。
> 这一层的价值在实施计划 §5.1 的差异化三件事里最硬的那一条：
> **上游只告诉你"藏好了"，我们告诉你"藏得到底成没成"**。

---

## 一、它比官方 API 多出来的三件事

| # | 能力 | 为什么必须有 |
| --- | --- | --- |
| 1 | **嵌入后往返自检**（`verified`） | hstego 的 `extract()` 失败时**不抛异常**，只往 stdout 打一行 `WARNING: message not found`，然后写出 **0 字节**结果文件。所以判定必须靠「输出不存在 / 0 字节 / sha256 不符」，**不能靠 try/except** |
| 2 | **失败自动换参重试** | JPEG 域实测提取失败率 **25%**，且与载体、载荷都相关、无法预测。已按 `q95 → q92 → q88` 重新编码载体重试，每次重试都重跑自检，全程记录进 `attempts[]` |

> **重试为什么有效（别误解成"提高质量就有更多容量"）**：重编码会把已经量化过一次的 DCT 系数
> 用更细的量化表再量化一遍（double quantization），系数值随之微扰，**等价于换了一张载体**，
> 于是 STC 在头部那 512 个位置上重新变得可解。
> 实测：sailboat q90 重编码到 q95 后容量仍是 972 B（容量没变），但自检从 `empty_output` 变成通过。
> 所以重试的价值不在容量，而在**扰动**。
| 3 | **真容量的口径** | `jpg_capacity()` 返回的是**密文预算**，不是"能藏多少原始字节"。密文长度 = `60 + len(zlib.compress(载荷, 9))`，直接拿容量数字当上限会让用户撞 `ValueError: Message too long` |

另外内建了 **PSNR / SSIM / 差分放大图** 与 **异步作业 + SSE 进度**——
重试链路可能跑到 1 分钟以上，同步 HTTP 会让浏览器或反代超时，而且计划要求"重试全程对用户可见"。

---

## 二、架构

```
                    ┌──────────────────────────────────────────┐
   HTTP  ──────────►│  backend/app.py        路由 / 校验 / 投递  │
                    └───────────────┬──────────────────────────┘
                                    │
                    ┌───────────────▼──────────────────────────┐
                    │  backend/service.py    编排放（可被 CLI 复用）│
                    └───────┬───────────────────────┬──────────┘
                            │                       │
              ┌─────────────▼──────────┐  ┌─────────▼─────────────┐
              │ backend/jobs.py        │  │ backend/storage.py    │
              │ 线程池 + 阶段 + SSE     │  │ 产物 token 化 + TTL    │
              └─────────────┬──────────┘  └───────────────────────┘
                            │
              ┌─────────────▼──────────────────────────────────────┐
              │ backend/engine/       ← 实施计划 §5.4 的接口层       │
              │   base.StegoEngine      embed() 返回 EmbedResult    │
              │                         └─ verified: bool  ★       │
              │   hstego_engine.py      本月实现（UNIWARD + STC）    │
              │   registry.py           diffusion 占位 → Phase 2 接入 │
              └─────────────┬──────────────────────────────────────┘
                            │  ctypes（全局串行锁保护）
              ┌─────────────▼──────────────────────────────────────┐
              │ hstegolib.py  +  hstego_stc_extension.so            │
              │               +  hstego_jpeg_toolbox_extension.so   │
              └────────────────────────────────────────────────────┘
```

**`StegoEngine` 抽象层的意义**：课题第二阶段要换成生成式（无载体）隐写，
届时只要实现同样签名的 `DiffusionEngine`，**上层路由与前端一行都不用改**。
`registry.py` 里的 `GenerativeEngineStub` 就是占着这个位置。

**并发约束（重要）**：`hstegolib` 用模块级 `random.seed()` + `random.shuffle()` 选嵌入位置，
**不是线程安全的**。所有原生调用都在 `engine/hstego_engine.py` 的 `_ENGINE_LOCK` 里串行执行，
作业线程池只是让排队与状态可见，不会真的并发跑两个嵌入。

---

## 三、跑起来

```bat
cd D:\projects\hstego\webapp
run-server.bat            :: 默认 127.0.0.1:8000
run-server.bat --reload   :: 开发模式，改代码自动重启
```

- **使用界面（推荐）**：<http://127.0.0.1:8000/> —— 面向普通用户的图形界面，见下节
- Swagger 交互文档（开发者）：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- 端到端自测：`run-test.bat`（用真实标准图跑完整 嵌入→自检→下载→提取 链路）

---

## 三之二、使用界面（`backend/web/`）

`/` 不再是 Swagger 的重定向，而是一个**给不写代码的人用的单页界面**：
纯静态（HTML + CSS + 原生 JS，无构建步骤、无框架、无 CDN），由 FastAPI 直接托管，
与接口同源，因此不存在 CORS 与跨域下载问题。

| 设计取舍 | 理由 |
| --- | --- |
| 全程不出现 JSON / 字段名 / 状态码 | 原 `/docs` 会把非技术用户直接劝退；界面只给「做了什么 / 成没成 / 下一步点哪」 |
| 两个标签页（藏 / 取）而非一页塞满 | 两个动作的心智模型完全不同，混在一起容易填错 |
| **选完图就自动估容量** | 容量取决于图像内容而非尺寸（同规格可差 3 倍），提前拦住「装不下」比让用户等 30 秒后失败好得多 |
| 结果只给大图 + 一个下载按钮 | 用户真正要的是那张载密图，不是 `stego_sha256` |
| 技术细节默认折叠 | 重试流水、PSNR、sha256 是答辩与复核用的证据，默认收起、需要时展开 |
| 不做差分图缩略图 | 实测 `diff.png` 在原尺寸下也几乎全黑（单点只改 ±1），缩略图无信息量；改为文字量化改动像素数 + 提供原图下载 |
| 失败文案按错误码映射 | 尤其 `not_found` 必须保持「口令错 / 图里本来没有 / 提取失败」三者并列，不能改写成「口令错误」 |

前端只依赖既有接口，未新增任何后端契约。它验证过的字段：`precheck.fits`、
`attempt_journal[]`、`metrics_vs_original.changed_samples`、`artifacts[].{kind,url,preview_url}`、
以及 `413 detail.{capacity_bytes,payload_cipher_bytes}`。

---

## 三之三、验证记录（界面层，2026-09-24）

用 Edge 无头模式 + CDP **真实驱动**界面（不是只截图）：真实触发 `change` 事件上传文件、
点真按钮、等真实作业、读回渲染结果。覆盖 8 步：

| 步骤 | 断言 |
| --- | --- |
| 初始状态 | 标题、引擎徽标「引擎就绪」、按钮禁用、容量面板隐藏 |
| 上传载体 | 文件名 `cover.png`、大小 `109.9 KB` 正确回显 |
| 填内容与口令 | 字节计数 57、按钮转为可用、就绪文案正确 |
| 自动容量预估 | 「≈ 1.4 KB / ≈ 128 字节 / ✓ 装得下，用掉 9%」、进度条宽度 9% |
| 点击嵌入 | 进度卡可见、阶段文案「正在把内容写进图片」 |
| 嵌入结果 | 结果卡 1 张、标题「藏好了，而且刚刚验证通过」、2 张对照图、2 个下载按钮、细节面板默认收起 |
| 切换并提取 | 取回文本与原文逐字一致、按钮为「复制内容 / 下载为文本文件」 |
| 错口令 | 结果标题「没取出内容来」、三选一提示 3 条、建议文案正确 |

全程 `Runtime.exceptionThrown` 与 `console.error` **均为空**。

这一轮实测暴露并修掉的 3 个真实缺陷（都不是猜的，是浏览器报出来的）：

1. `ui.onDone is not a function` —— 回调挂在 `opts` 上却从 `opts.ui` 取，结果卡永远不渲染；
2. `[hidden]` 被类选择器的 `display:flex` 覆盖 —— 空状态里同时显示了「点击选择图片」和已选文件框。
   修法是全局 `[hidden] { display: none !important; }`（**类选择器优先级高于 UA 的 `[hidden]` 规则**）；
3. `actions.unshift is not a function` —— 把 DOM 元素当数组用了，改成 `appendChild` 按顺序构建。

同类界面以后照这个顺序验：先跑接口 e2e 确认字段，再上无头浏览器驱动交互，最后才看截图。


首次使用前装依赖（工程 `.venv` 里已有算法依赖，只缺 Web 层）：

```bat
..\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 四、API 契约

统一前缀 `/api/v1`。错误统一为 `{"code", "message", "detail"}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 引擎可用性、原生扩展加载状态、`MAX_PAYLOAD`、工作目录可写性 |
| GET | `/engines` | 引擎列表（`hstego` 可用，`diffusion` 占位） |
| POST | `/capacity` | **同步**容量预估。表单：`cover`、可选 `payload_file` / `payload_text` |
| POST | `/embed` | 投递嵌入作业 → **202** `{job_id, status_url, events_url, precheck}` |
| POST | `/extract` | 投递提取作业 → **202** |
| GET | `/jobs?limit=20` | 最近作业 |
| GET | `/jobs/{job_id}` | 作业状态：`status / stage / progress / message / logs / result / error` |
| GET | `/jobs/{job_id}/events` | **SSE** 进度流（`progress` → `done`） |
| GET | `/artifacts/{token}` | 下载产物，`?inline=1` 内联展示 |
| GET | `/artifacts/{token}/preview` | 图像预览，`?max_side=1600` |

### `/embed` 表单字段

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `cover` | 必填 | 载体图（png / pgm / tif → 空间域；jpg → 压缩域，按**内容**判定而非后缀） |
| `password` | 必填 | 口令。同时决定嵌入位置（种子）与 AES 密钥 |
| `payload_file` / `payload_text` | 二选一 | 载荷 |
| `engine_name` | `hstego` | 引擎注册名 |
| `include_diff` | `true` | 是否生成差分放大图 |
| `diff_gain` | `20` | 差分放大倍数（UNIWARD 单点只改 ±1，不放大看不见） |
| `precheck` | `true` | 投递前先做容量预检，超限立刻 **413**，不用等 30 秒作业白跑 |

### 嵌入结果里的关键字段

```jsonc
{
  "ok": true,
  "verified": true,              // ★ 嵌入后自检是否通过；只有 true 才代表"取得回来"
  "domain": "jpeg", "algorithm": "J-UNIWARD",
  "capacity": { "capacity_bytes": 972, "cipher_overhead_bytes": 60,
                "max_incompressible_payload_bytes": 912, "fits": true },
  "attempts": [                  // 每次尝试的完整证据
    { "index": 0, "quality": null, "verified": false, "failure_reason": "empty_output", "elapsed_seconds": 9.4 },
    { "index": 1, "quality": 95,   "verified": true,  "failure_reason": null,           "elapsed_seconds": 11.2 }
  ],
  "chosen_attempt": 1,
  "metrics": { "psnr_db": 61.27, "ssim": 0.999923, "max_abs_diff": 1, "changed_ratio": 0.0009 },
  "metrics_vs_original": { ... },      // 若重编码过载体，这一份才是"用户上传的那张 vs 载密图"
  "retry_used": true,
  "artifacts": [ { "kind": "stego", "url": "/api/v1/artifacts/xxx", "sha256": "..." }, ... ]
}
```

`artifacts[].kind` ∈ `cover` / `payload` / `stego` / `diff` / `extracted`。

### 提取失败的语义

`extract` 失败时作业 `status = failed`、`error.code = not_found`、文案为三者并列：

> 未提取到消息。可能原因：① 口令错误；② 该图片中确实没有消息；③ 提取失败。

**不要**把它改写成"口令错误"——在 hstego 里这三种症状完全相同（都是 0 字节输出 + 一行 stdout WARNING），
无法从现象区分。

---

## 五、环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HSTEGO_PROJECT_ROOT` | `webapp/..` | hstegolib.py 所在目录 |
| `HSTEGO_WORK_ROOT` | `<工程根>/output/webapp` | 上传件与产物的工作目录 |
| `HSTEGO_PORT` / `HSTEGO_HOST` | `8000` / `127.0.0.1` | 监听地址 |
| `HSTEGO_MAX_UPLOAD_BYTES` | 64 MB | 单文件上限 |
| `HSTEGO_MAX_PAYLOAD_BYTES` | 8 MB | 载荷上限 |
| `HSTEGO_ARTIFACT_TTL` | 21600 | 产物保留秒数，过期自动回收 |
| `HSTEGO_JPEG_RETRY_QUALITIES` | `95,92,88` | 重试质量阶梯 |
| `HSTEGO_JPEG_SUBSAMPLING` | `0`（4:4:4） | 重编码时的色度子采样 |
| `HSTEGO_MAX_ATTEMPTS` | 4 | 同一载荷最多尝试次数 |
| `HSTEGO_CORS_ORIGINS` | `127.0.0.1:5173,localhost:5173` | 前端 dev server 白名单 |

---

## 六、验证记录（2026-09-23 实测）

| 脚本 | 覆盖 | 结果 |
| --- | --- | --- |
| `run-test.bat`（`tests/smoke_test.py`） | health / 引擎列表 / 容量口径 / 空间域与压缩域各一次完整往返 / 超限 413 / 错口令 not_found / 差分图 / 产物下载与预览 | **35 项全通过，29 s** |
| `tests/retry_ladder_test.py` | 用 2026-09-23 基线里**已知必失败**的（sailboat q90 + 128 B 真随机载荷）重放，验证重试链路 | **第 1 次 `empty_output` → 第 2 次（q95）通过**，verified=True，PSNR 65.75 dB，全程 34 s |
| `tests/live_check.py` | 对**真实 uvicorn 服务**走真 HTTP：SSE 进度流、文本载荷往返、差分图预览、错误口令 | 见下 |

重试链路的实测流水（后端最该被看见的一段）：

```
  #      质量      容量      密文      自检              失败原因       耗时
  1      原始     972     199     未通过      empty_output    15.0s
  2      95     972     199      通过                 -    15.6s
结论：verified=True ｜ 采用第 2 次尝试 ｜ retry_used=True
```

单次嵌入约 15 s（3 次 scrypt n=2^18 派生 + 自检再提取一次），
所以**必须**是异步作业 + 进度推送，同步 HTTP 会在重试时超时。

空间域实测：PSNR 78.4 dB / SSIM 0.9999984 / 最大改动 1 / 改动像素比例 0.095%
压缩域实测：PSNR 63.9 dB / SSIM 0.9999374 / 最大改动 4 / 改动像素比例 2.1%

---

## 七、已知限制

1. **JPEG 域失败率 25% 是上游行为**，不是本后端的 bug。本层做的是"兜住 + 说清楚"，
   并把重试过程作为可复现证据留存（`attempts[]` + 每次尝试的载密图都在 `output/webapp/jobs/<job_id>/attemptN/`）。
2. **提取结果不含原始文件名**——hstego 的密文里只存内容，不存元数据，所以下载名是
   `extracted.txt` / `extracted.bin`。若将来需要，可在生成式引擎里把文件名一并编码。
3. **容量与图像内容强相关**：同为 512×512 q=90，`splash` 只有 460 B，`baboon` 有 1532 B，差 3.3 倍。
   UI 必须按用户实际选的文件算，不能按尺寸估。
4. 单机串行：`_ENGINE_LOCK` 决定同一时刻只有一个嵌入/提取在跑，QPS 上限约 1/10s。

---

## 八、目录

| 路径 | 职责 |
| --- | --- |
| `backend/app.py` | FastAPI 应用与全部路由，并在 `/` 托管使用界面 |
| `backend/web/index.html` | 使用界面骨架（藏/取两个标签页，各三步表单） |
| `backend/web/app.js` | 界面交互：拖放上传、自动容量预估、SSE 进度、结果渲染、错误码 → 人话映射 |
| `backend/web/styles.css` | 界面样式（浅色，纯本地，无 CDN） |
| `backend/service.py` | 编排放：上传件 → 引擎 → 产物登记 |
| `backend/jobs.py` | 作业对象、线程池、进度/日志、SSE 唤醒 |
| `backend/storage.py` | 产物存储、token、TTL 回收、文件名消毒 |
| `backend/engine/base.py` | `StegoEngine` 抽象接口 + 结果数据结构 |
| `backend/engine/hstego_engine.py` | HStegoEngine：自检、重试、容量口径、指标 |
| `backend/engine/registry.py` | 引擎注册表 + 生成式引擎占位 |
| `backend/metrics.py` | PSNR / SSIM / 差分放大图 |
| `backend/schemas.py` | Pydantic 契约模型 |
| `backend/config.py` | 配置（可被环境变量覆盖） |
| `backend/errors.py` | 错误码与异常 |
| `tests/smoke_test.py` | 端到端冒烟测试（真实图 + 真实往返） |
| `run-server.bat` / `run-test.bat` | 一键启动 / 一键自测 |

---

## 九、合规声明

隐写技术具有双用途属性。**本项目仅用于学术研究与教学演示**，不得用于任何非法目的。
演示仅使用公开学术测试图像（USC-SIPI 等）或自有图片；
不在公开网络传输任何真实敏感信息；不针对具体平台设计规避内容审核的工具。
