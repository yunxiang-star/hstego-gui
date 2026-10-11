# 第三方组件与授权声明

本仓库为**独立工程**，不包含上游源码的拷贝。但它建立在若干第三方成果之上，
其中一部分以**预编译产物**的形式随仓库分发。此处逐项说明授权与出处。

---

## 1. hstego —— 算法基座

| 项 | 内容 |
| --- | --- |
| 项目 | [daniellerch/hstego](https://github.com/daniellerch/hstego) |
| 作者 | Daniel Lerch（奥地利 Innsbruck 大学，Böhme 团队） |
| 许可证 | **MIT License** |
| 版权声明 | Copyright (c) 2020 Daniel Lerch \<dlerch@gmail.com\> |
| 本仓库中的形态 | **不直接收录其源码**。`setup.bat` 在用户本机按需克隆上游到 `hstego-runtime/`（该目录已在 `.gitignore` 中排除）。 |

### 随仓库分发的编译产物

`runtime/hstego_stc_extension.so` 与 `runtime/hstego_jpeg_toolbox_extension.so`
是**基于上游 hstego 源码在本机手工编译得到的二进制扩展**（合计约 170 KB），
刻意入库以便换机器克隆后无需重新编译（原因见
[`docs/02_JPEG_Toolbox攻坚报告.md`](../docs/02_JPEG_Toolbox攻坚报告.md)）。

由于上游为 MIT 许可证，允许以源码或二进制形式复制、修改、再分发，
**前提是保留上述版权声明与许可声明**。本文件即承担该保留义务。

> MIT 上游的具体条款原文见上游仓库根目录的 `LICENSE.txt`。

---

## 2. libjpeg / JPEG Toolbox —— 间接依赖

上游 hstego 的 `src/` 内含 **libjpeg** 源码（约 10 MB），用于构建压缩域所需的
JPEG Toolbox 扩展。其许可证为
[JPEG License](https://www.ijg.org/)（宽松，允许自由使用与再分发，要求保留版权声明）。

本仓库**未收录**该源码，仅在编译产物中链接其代码。若你需要从源码重建扩展，
`setup.bat` 会经上游仓库间接到该组件。

---

## 3. Python 运行时依赖

`runtime/requirements-hstego.txt` 与 `webapp/requirements.txt` 声明的依赖
（NumPy、Pillow、FastAPI、Uvicorn 等）**不随本仓库分发**，由 pip 在用户环境按各自许可证安装。
详见各包的官方授权条款。

---

## 4. 测试与演示用图像

`evidence/` 与 `docs/` 中出现的测试图像来自 **USC-SIPI 标准图像库**
（University of Southern California, Signal and Image Processing Institute），
或其自有/公开测试图。USC-SIPI 图像库为学术研究公开数据集，仅用于本项目的
往返一致性与容量评测，不作商业用途。

---

## 5. 本仓库自身

`webapp/`、`tools/`、`docs/`、`notes/`、`evidence/`、`agent-config/`
以及 `README.md`、`setup.bat` 等本工程自行创作的内容，
以 **MIT License** 授权，条款见仓库根目录 [`LICENSE`](../LICENSE)。

---

*若你认为本仓库中有任何内容侵犯了你的权利，请开 Issue 说明，我们会立即处理。*
