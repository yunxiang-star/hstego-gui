# tools/ — 脚本与调试配置

## 编译

| 文件 | 用途 |
| --- | --- |
| `build_jpeg_toolbox.py` | **手工编译 JPEG Toolbox 扩展**。自带 MSVC / Windows SDK 工具链定位（glob 查找，不依赖 setuptools、不碰 `reg.exe`），把 `jpeg_toolbox_extension.c` 与 46 个 libjpeg 源文件**在同一次 `cl` 调用里**一起编 —— 全工程只有一套编译器 + 一套 CRT，`LNK2005/LNK1169` 冲突在物理上不可能发生。3 秒编完，无需联网。 |
| `build_native.py` | 早期的编译尝试（保留作为过程记录，已被 `build_jpeg_toolbox.py` 取代） |
| `build_ext.bat` / `build-ext.bat` | 用 `vswhere` 自动定位 Visual Studio 后跑 `setup-win.py build_ext --inplace`。**上游路线，本机会失败**，见 `docs/02_*.md` |
| `test_jpeg_toolbox.py` | 编译后的验收：`CDLL` 直接加载、检查导出符号、`read_file()` 返回结构、J-UNIWARD 往返 sha256 |

## 运行（需先由 `setup.bat` 铺好环境）

| 文件 | 用途 |
| --- | --- |
| `run-gui.bat` | 启动上游自带的 Tkinter 图形界面 |
| `run-cli.bat` | 命令行：`capacity` / `embed` / `extract` |
| `selftest.bat` + `selftest.py` | 一键跑嵌入↔提取往返自测 |
| `compare.bat` + `compare.py` | 载体 / 载密图对比，输出 MSE / PSNR / 改动像素比例 + 并排对比图 |

## 评测与基准

| 文件 | 用途 |
| --- | --- |
| `capacity_bench.py` | 容量基准。⚠️ 它用 `rng.normal(0, 9)` 生成**合成噪声图**，非零 DCT 系数海量，测出的数字**系统性虚高**，结果见 `evidence/容量基准_合成噪声图_已作废.txt`。**别再用它出结论**，改用真实照片。 |
| `baseline_eval.py` | **正式的评测基线脚本**：9 张 USC-SIPI 标准图 × 空间域/压缩域各一次往返，输出 PSNR / SSIM / 改动像素比例 / 耗时 / 往返是否一致。结果见 `evidence/评测基线报告.md` |

## VSCode

`vscode/` 下是从原工程拷来的 `.vscode` 三件套（`launch.json` / `settings.json` / `tasks.json`），
预置 6 个调试配置（启动 GUI、可单步进库代码的 GUI、三个 CLI 任务、运行当前文件）。
**里面的路径写死为 `D:\projects\hstego`，搬到别处要改。**

---

### 复现评测基线

```bat
hstego-runtime\.venv\Scripts\python.exe tools\baseline_eval.py
```

跑完约 260 秒，输出 `baseline_report.md` + `baseline_results.csv`。
预期结果：空间域 9/9 通过、压缩域 6/8 通过（**有 2 条必然失败，这是上游缺陷不是你的环境问题**）。
