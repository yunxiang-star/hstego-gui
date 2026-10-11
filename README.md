# HStego 图像隐写 · 工作台与应用层

> 课题《基于 AIGC 模型的生成式信息隐藏应用程序》的**第一阶段工程产物**。
> 基座是 Innsbruck 大学 Böhme 团队的开源工具 [hstego](https://github.com/daniellerch/hstego)
> （Fridrich 团队 UNIWARD 定代价函数 + STC 最小失真编码的实现）。
>
> **本仓库收录的不是 hstego 本身，而是我们在它之上做出来的一切**：
> 跑通它的编译、把它的 API 陷阱摸清、写出一个真正可演示的 Web 应用、
> 以及支撑答辩的全部实测数据。

---

## 一、这个仓库是什么

**上游只告诉你「藏好了」；我们告诉你「藏得到底成没成」。**

`hstego` 的 `extract()` 在某些载体上会**确定性失败，而且完全静默**——
不抛异常、不返回错误，只往 stdout 打一行 `WARNING: message not found`，
然后**正常写出一个 0 字节的"结果文件"**。实测 JPEG 压缩域失败率 **25%**。

任何直接调用 `hstego` 写出来的应用，都会在四分之一的情况下给用户一个损坏的结果而**毫不自知**。
本仓库的核心价值就是这件事：**发现它、量化它、兜住它、并且把证据留下来。**

---

## 二、核心成果一览

| # | 成果 | 关键数字 / 证据 |
| --- | --- | --- |
| 1 | **手工编译两个原生扩展**（STC 引擎 + JPEG Toolbox），绕过 `setup.py` 定位 Visual Studio 失败与 `LNK2005/LNK1169` CRT 冲突 | 产物见 `runtime/`，3 秒内编完，无需联网。踩坑记录：`notes/经验_hstego原生扩展编译.md` |
| 2 | **双域评测基线**：9 张 USC-SIPI 标准图 × 空间域/压缩域 | 空间域往返 **9/9**、PSNR 均值 **79.52 dB**；压缩域往返 **6/8（失败率 25%）**、PSNR 均值 **61.27 dB** |
| 3 | **定位 J-UNIWARD 静默失败缺陷**（六步排除法，非推测） | 失败点锁定在通道 0 前 512 个嵌入位置里的 32 字节头部，`decrypt_header()` 抛 `MAC check failed` 被 `except` 吞掉。报告：`docs/03_J-UNIWARD提取可靠性缺陷报告.md` |
| 4 | **FastAPI 应用层**：嵌入后往返自检 + 失败自动重参数 + 真容量口径 + PSNR/SSIM + 异步作业/SSE | 冒烟测试 **35 项全通过**；重试链路用"已知必失败组合"实证有效。代码：`webapp/` |
| 5 | **面向非技术用户的单页界面**（无框架、无构建、无 CDN） | 用无头 Edge + CDP **真实驱动**验证 8 步流程，`Runtime.exceptionThrown` 为空 |
| 6 | **可复现的失败证据** | `evidence/失败证据_JUNIWARD/` 里放着两个失败案例的原始载体、载密图、128 B 载荷，以及**0 字节的提取结果** |

---

## 三、30 秒跑起来

### 前置条件

- Windows + Python 3.11–3.13（本项目在 3.13.12 上验证）
- 能访问 GitHub（要拉上游 hstego 源码）

### 做法：双击 `setup.bat`

它会自动完成：克隆上游 `hstego` 到 `hstego-runtime\` → 覆盖我们预编译好的两个 `.so`
→ 建虚拟环境 → 按镜像源装齐算法依赖与 Web 依赖 → 把 `webapp\` 接进去。

装完直接双击：

```bat
hstego-runtime\webapp\run-server.bat     :: 启动 Web 应用，浏览器开 http://127.0.0.1:8000/
hstego-runtime\run-gui.bat               :: 启动 hstego 自带的 Tkinter 图形界面
hstego-runtime\selftest.bat              :: 一键跑嵌入↔提取往返自测
```

> **为什么要 `setup.bat` 而不是直接把上游源码放进仓库**：
> 上游 `src/` 里有 10 MB 的 libjpeg 源码，属于他人成果且已在 GitHub 公开，
> 复制进来只会让"哪些是学生做的"变模糊。仓库只保留**我们自己编出来的产物**（`runtime/*.so`，170 KB），
> 其余按需拉取。

### 不装也能看的部分

`docs/` 里的报告、`evidence/` 里的实测数据、`notes/` 里的经验记录，都是纯文本/图片，克隆下来即可阅读。

---

## 四、仓库结构

| 路径 | 是什么 | 谁写的 |
| --- | --- | --- |
| **`webapp/`** | **FastAPI 应用层**（后端 + 单页界面 + 测试），本课题的主战场 | 我们 |
| `webapp/README.md` | 应用层完整说明书：架构、API 契约、字段清单、验证记录、已知限制 | 我们 |
| **`tools/`** | 编译脚本、自测脚本、容量基准、评测基线脚本、VSCode 调试配置 | 我们 |
| **`runtime/`** | **预编译的原生扩展**（`.so`）+ 算法依赖清单 | 我们编译的产物 |
| **`docs/`** | 实施计划、攻坚报告、缺陷报告、思维导图、上游说明 | 我们 |
| **`evidence/`** | 评测基线原始数据、失败证据（含 0 字节提取结果）、构建日志 | 实测产物 |
| **`notes/`** | **经验沉淀**：把上面所有坑写成可复用的操作手册 | 我们 |
| `agent-config/` | 给 AI 编程助手（opencode）用的项目说明书与子智能体定义 | 我们 |

---

## 五、三条最该被问到、也最能体现深度的事

### 1. 为什么必须有「嵌入后往返自检」，而且判据不能是 `try/except`

```python
embed(cover, msg, pwd, stego)        # 官方调用，返回成功
extract(stego, pwd, tmp)             # 立刻自己取一次
失败 := tmp 不存在 or 0 字节 or sha256(tmp) != sha256(msg)
```

因为 `extract()` 失败时**不抛异常**，只 `print("WARNING: message not found")` 到 **stdout**
（注意不是 stderr），然后正常写出 **0 字节**结果文件。
`try/except` 抓不到任何东西，只能靠**产物**判定。

### 2. 重试为什么有效 —— 是「扰动」，不是「容量」

JPEG 域失败后换编码质量重试（`q95 → q92 → q88 → 换载体`）。
机制是重编码把已量化过一次的 DCT 系数用更细的量化表**再量化一遍**（double quantization），
系数被扰动，**等价于换了一张载体**。

> 实测：sailboat q90 → q95，**容量仍是 972 B（一点没变）**，但自检从 `empty_output` 变成通过。
> 所以答辩时**不要**说成"质量更高所以容量更大"——那是错的。

### 3. 容量必须按「密文预算」口径算，而且要用用户实际的文件算

```
密文长度 = 60 + len(zlib.compress(载荷, 9))
           └ salt16 + nonce16 + tag16 + magic4 + len8 = 60 字节固定开销
可藏原始载荷上限（不可压缩） ≈ jpg_capacity() - 71
```

`jpg_capacity()` 返回的是**密文预算**，不是"能藏多少原始字节"。
而且容量由**图像内容**决定，不是尺寸：同为 512×512 q90，
`splash` 只有 **460 B**、`baboon` 有 **1532 B**，**差 3.3 倍**。
所以界面必须在用户选完图后立刻按**那张图**算容量，而不是给一个尺寸对照表。

---

## 六、实测基线（可直接引用的数字）

载荷：真随机 128 B（不可压缩）｜口令 `baseline-pwd-2026`｜JPEG q=90 4:4:4｜容量上限 5%

| 项 | 空间域 PNG / S-UNIWARD | 压缩域 JPEG / J-UNIWARD |
| --- | --- | --- |
| 往返一致性（9 张 SIPI 标准图） | **9 / 9** | **6 / 8（失败率 25%）** |
| PSNR 均值 | 79.52 dB（72.08–83.41） | 61.27 dB（58.24–62.99） |
| SSIM 最低 | 0.999984 | 0.999699 |
| 单次嵌入耗时 | 5.5–7.7 s | 6–17 s（带自检约 15 s） |
| 最大改动 / 改动像素比例 | ±1 / 0.03–0.40% | ±5 / 2.3–2.5% |

重试链路实证（sailboat q90 + 128 B 真随机载荷）：

```
  #    质量    容量   密文   自检      失败原因        耗时
  1    原始    972    199   未通过    empty_output   15.0s
  2    95      972    199   通过      -              15.6s
→ verified=True，采用第 2 次尝试，PSNR 65.75 dB
```

真实照片容量（512×512, q90, 4:4:4）：`splash` 460 B｜`baboon` 1532 B｜`airplane` 508 B｜
`sailboat` 972 B｜`peppers` 700 B｜`barbara` 516 B。

> ⚠️ `evidence/容量基准_合成噪声图_已作废.txt` 里那组按尺寸递增的数字（512×512→852 B 等）
> 是用高斯噪声合成图测的，数字**系统性虚高**，已作废。真实照片容量**只由纹理决定**。

---

## 七、文档索引

| 文档 | 内容 |
| --- | --- |
| [`docs/01_一个月实施计划.md`](docs/01_一个月实施计划.md) | 完整的一个月路线图：阶段划分、论文页面级阅读表、术语表、评价指标、风险 |
| [`docs/02_JPEG_Toolbox攻坚报告.md`](docs/02_JPEG_Toolbox攻坚报告.md) | 为什么 `setup.py` 编不过、`LNK2005` 的真因、手工编译路线的每一步 |
| [`docs/03_J-UNIWARD提取可靠性缺陷报告.md`](docs/03_J-UNIWARD提取可靠性缺陷报告.md) | 六步排除法定位静默失败，失败环节精确到 32 字节头部 |
| [`docs/04_hstegolib_API速查.md`](docs/04_hstegolib_API速查.md) | 引擎类、`embed/extract` 参数顺序、容量函数、最小可运行示例 |
| [`notes/经验_hstego原生扩展编译.md`](notes/经验_hstego原生扩展编译.md) | 编译侧 + 应用侧全部铁律（可直接照做） |
| [`notes/经验_hstego应用层封装.md`](notes/经验_hstego应用层封装.md) | 封装成 Web 服务的四条硬规则、前端字段清单、界面审美取舍、全部踩坑表 |
| [`webapp/README.md`](webapp/README.md) | API 契约、SSE 事件、错误语义、环境变量、验证记录 |
| [`docs/隐写编码_概念思维导图.svg`](docs/隐写编码_概念思维导图.svg) | 概念关系可视化 |
| [`docs/架构图_三层结构.png`](docs/架构图_三层结构.png) | 界面 / 后端 / hstego 三层架构图 |
| [`docs/B站隐写科普视频清单.html`](docs/B站隐写科普视频清单.html) | 入门视频合集 |
| [`docs/hstego上游原始说明.md`](docs/hstego上游原始说明.md) | 上游 README（含论文引用），只读参考 |

---

## 八、技术背景（够用版）

- **UNIWARD**：给每个像素/系数算一个"改动代价"——纹理复杂处便宜、平滑处昂贵。
  输出的是**代价图**，不是"改哪里"。
- **STC（Syndrome-Trellis Codes）**：在代价已知的前提下，用维特比算法找出
  总失真最小的嵌入方案。本质是纠错码的变体。**当黑箱用，不啃数学。**
- **为什么容量限制在 5%**：超过这个嵌入率，基于深度学习的隐写分析器
  （如 [Aletheia](https://github.com/daniellerch/aletheia)）能可靠检出。

核心论文：

| 论文 | 作者 | 作用 |
| --- | --- | --- |
| [Universal Distortion Function for Steganography in an Arbitrary Domain](https://doi.org/10.1186/1687-417X-2014-1) | Holub, Fridrich, Denemark | UNIWARD 原始论文 |
| [Minimizing Additive Distortion in Steganography using Syndrome-Trellis Codes](https://doi.org/10.1109/TIFS.2011.2134094) | Filler, Judas, Fridrich | STC 原始论文 |
| [JPEG Steganography With Estimated Side-Information](https://ieeexplore.ieee.org/document/8746719) | Li, Chen, Zhang 等 | J-UNIWARD + 代价极化 |

---

## 九、下一步（课题方向）

传统隐写这条线**已经跑通并且可演示**了。接下来往生成式推进，三条路难度与深度差别很大：

1. 用扩散模型**生成载体图**（生成即隐写）
2. 用模型**改造成本函数**（替换 UNIWARD 的手工代价）
3. 让隐写与生成**联合优化**

`webapp/backend/engine/registry.py` 里已经留了一个 `GenerativeEngineStub`
（`available=false`）占住生成式引擎的位置——**换算法时上层路由与前端一行都不用改**
这件事是**可验证的架构事实**，不是口号。

---

## 十、合规声明

隐写技术具有**双用途属性**。本项目**仅用于学术研究与教学演示**，不得用于任何非法目的。

- 演示只使用公开学术测试图像（USC-SIPI 等）或自有图片；
- 不在公开网络传输任何真实敏感信息；
- 不针对具体平台设计规避内容审核的工具。

上游 hstego 与 libjpeg 的授权见 [`docs/hstego上游原始说明.md`](docs/hstego上游原始说明.md) 与各上游仓库。

---

## 十一、开源许可证

本仓库以 **MIT License** 授权，见 [`LICENSE`](LICENSE)。你可以自由使用、修改、分发，
包括商业用途，只需保留版权声明。

上游 `hstego` 同为 MIT，其版权声明（Copyright (c) 2020 Daniel Lerch）与
`runtime/*.so` 等编译产物的来源说明，统一收录在
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

---

*工程搭建 2026-09-21 — 2026-09-24*
