# JPEG Toolbox 攻克报告

> 2026-09-23 · 针对 hstego v0.6.1 的 JPEG Toolbox 原生扩展在 Windows 下的编译失败问题
> 状态：**已攻克**，`import hstegolib` 通过，J-UNIWARD 藏取往返实测成功

---

## 一、结论先行

| 项目 | 之前（2026-09-20） | 现在 |
| --- | --- | --- |
| `hstego_jpeg_toolbox_extension.so` | ❌ LNK1169 链接失败 | ✅ 110 KB，3.1 秒编出 |
| `import hstegolib` | ❌ RuntimeError | ✅ 成功（两个扩展都加载） |
| 读 DCT 系数 / 量化表 | 不可用 | ✅ Y 通道 (64,64,8,8)，非零 AC 125877 个 |
| J-UNIWARD 藏取往返 | 不可用 | ✅ 96 字节消息完整取回，PSNR 64.56 dB |
| 挡住后续所有工作？ | 是 | **不再是** |

**一句话**：不需要 MATLAB、不需要 WSL、不需要联网、不需要官方预编译二进制——
仓库里本来就带着完整 libjpeg 9c 源码，把它的 46 个 .c 文件和扩展源码在**同一次编译**里一起编，
CRT 冲突在物理上就不可能发生。

---

## 二、失败根因（大白话版）

### 2.1 之前的路走错了：非要去链接一个「别人编的」静态库

仓库里 `src/jpeg-9c-win/Lib/static_x64/jpeg.lib` 是一个**预编译好的**二进制。
它由别人用 **MSVC 2017** 编译，它的目标文件里刻着一行指令：*"链接我时请用静态版 UCRT（libucrt.lib）"*。

而你自己的扩展代码编译时带进来的是**导入版** UCRT（ucrt.lib → 调 api-ms-win-crt-*.dll）。
两套 CRT 的定义同时进来 → 同一个 `exit`、`fflush`、`__acrt_iob_func` 被定义了两次：

```
libucrt.lib(exit.obj) : error LNK2005: exit 已经在 ucrt.lib(...) 中定义
...
fatal error LNK1169: 找到一个或多个多重定义的符号
```

用「C 语言 vs Python」打比方：一个是**自己实现所有函数**的静态库（自带全部零件），
另一个是**依赖系统动态库**的编译方式（去敲隔壁的门）。两边的门牌号一样但门不一样，链接器就懵了。

### 2.2 更要命的一点：之前那个「修复」其实一行都没生效

原 `build_native.py` 里写了三个想压掉重复定义的参数：

```
/NODEFAULTLIB:libucrt /NODEFAULTLIB:libcmt /NODEFAULTLIB:msvcrt
```

但编译器在日志里明确说了：

```
cl: 命令行 warning D9002 : 忽略未知选项"/NODEFAULTLIB:libucrt"
cl: 命令行 warning D9002 : 忽略未知选项"/NODEFAULTLIB:libcmt"
cl: 命令行 warning D9002 : 忽略未知选项"/NODEFAULTLIB:msvcrt"
```

**cl.exe 直接不认这三个参数，全部丢弃。** 这类链接器参数必须写在 `/link` 之后才会被传给链接器。
所以当时的构建脚本等于「在错误的路上做了一次无效的尝试」——不是参数没调好，是参数根本没上车。

> 教训：`cl` 报的 warning 里有 D9002（忽略未知选项）时，**必须当成 error 看**。它会静默吞掉你所有的链接器意图。

### 2.3 为什么「重编 libjpeg」是最干净的解法

`jpeg.lib` 那个坑的本质是**跨编译器 + 跨 CRT 的二进制拼接**。
只要把 libjpeg 的 C 源码拿过来，和自己的扩展**在同一个编译器、同一套 CRT、同一次调用里**编，
「不一致」这件事就没有存在的余地了——这是从根上消除问题，而不是把报错一个个按下去。

而这份源码**就在仓库里**：`src/jpeg-9c-win/jpeg-9c-src/`，187 个文件，46 个库源文件一个不缺。

---

## 三、三条备选路的实测结论

| 路线 | 结论 | 原因 |
| --- | --- | --- |
| ① 官方 Windows v0.6.1 预编译包 | **不能解决此问题** | 那是 PyInstaller 打包的**独立 exe**（`hstego-0.6.1-win.amd64.exe`），不是可被你的 Python 程序 import 的库。里面的扩展按作者当时的 Python 版本编译，导入表指向 `python3XX.dll`，在你 3.13 进程里 `CDLL` 加载会直接失败。可用作**功能对照参照**，不能当依赖。 |
| ② WSL / Linux 构建 | 可行但性价比低 | 要维护两套环境，产物是 ELF 不是 PE，Windows 下的 Python 加载不了；等于为了绕开一个链接问题去换操作系统 |
| ③ **重编 libjpeg 替换静态库** | ✅ **采用** | 源码在仓库里，3.1 秒编完，零外部依赖，一次解决 |
| （原计划未列）④ 用 Python 版 `jpegio` 替代 | 可用但需改写 | 功能等价（同出 Fridrich 实验室代码血脉），但要改 `hstegolib.py` 的调用层，风险大于收益 |

---

## 四、怎么做的（可复现）

### 4.1 关键参数

```bat
cl /nologo /LD /O2 /MD ^
   /I src\jpeg-9c-win\jpeg-9c-src ^
   /I src\jpeg-9c-win\Include ^
   /I <build>\ ^
   /I <Python>\include ^
   src\jpeg_toolbox_extension.c ^
   <46 个 libjpeg 源文件> ^
   /link /OUT:hstego_jpeg_toolbox_extension.so python313.lib
```

要点四条：

1. **`/MD`** —— 必须与 CPython 一致（动态 UCRT）。这是整件事的核心。
2. **`/link` 写在最后** —— 所有链接器参数放它后面，否则又被 D9002 静默吞掉。
3. **`python313.lib` 显式链接** —— 扩展用了 Python C-API（`PyDict_New` 等），
   但源码里没有 `#pragma comment(lib,...)`，必须手动挂。
   （对比：STC 扩展是纯 C++、不碰 Python C-API，所以它当初不需要这个也能编过——
   这也解释了为什么「STC 成功、JPEG 失败」，工具链其实一直是好的。）
4. **`jconfig.h`** —— 这是唯一缺的文件。从 `Include/jconfig.h` 拷一份即可
   （已验证它与 `jpeg-9c-src/jconfig.vc` 内容完全一致）。

### 4.2 一个隐藏的坑：两套头文件

`Include/` 和 `jpeg-9c-src/` 里各有一份 `jpeglib.h`/`jmorecfg.h`/……，
`md5` 不同，一度让人怀疑要不要担心 ABI 不一致。
逐行比对后确认：**内容完全相同，只差换行符（CRLF vs LF）**。
所以不存在结构体布局错位风险，但为了稳妥，构建脚本统一用一套（`/I` 都指过去 + 构建目录放 `jconfig.h`）。

### 4.3 产出物

| 文件 | 作用 |
| --- | --- |
| `build_jpeg_toolbox.py` | 一键构建脚本（自动定位 MSVC / Windows SDK） |
| `hstego-src/hstego_jpeg_toolbox_extension.so` | 扩展本体，110 KB |
| `test_jpeg_toolbox.py` | 端到端验证脚本（DCT 读取 + 藏取往返 + 差异统计） |
| `build_jpeg_log.txt` / `test_jpeg_log.txt` | 完整日志 |

重跑：`python build_jpeg_toolbox.py && python test_jpeg_toolbox.py`

---

## 五、验证证据

```
[1] ctypes 直接加载 DLL      LOADED OK, handle 7ffc7b460000
[3] 读 DCT 系数              返回 dict，18 个 key
                             coef_arrays: 3 通道，Y = (64,64,8,8)
                             quant_tables: 2 张，Y 直流步长 = 3
                             Y 非零 AC 系数 = 125877
[4] import hstegolib         [OK]（JPEG + STC 两个扩展都加载）
    embed                    17.34s，102089 -> 102085 字节
    extract                  5.69s
    消息 sha256              711ebe1489d82503 == 711ebe1489d82503  ✓ 完全一致
[5] DCT 改动统计             改动 234 个系数 / 共 262144 个（0.0893%）
                             改动幅度集合 = {±1}   ← 教科书级的最小失真特征
    像素域 PSNR              64.56 dB
```

第 [5] 项特别值得留着——**这就是答辩时的核心论据**：
改动幅度只有 ±1、只动了万分之九的位置、PSNR 64.5 dB，
每一个数字都是「最小失真框架」在起作用的直接证据。朴素 LSB 替换做不到这个分布。

---

## 六、顺带发现的两个新问题（都会影响 GUI）

### 6.1 容量：先纠正一个我自己算错的数

`jpg_capacity()` **内部已经乘过 `MAX_PAYLOAD = 0.05`**了（在 `jpg_channel_capacity()` 里）。
所以它返回的就是**实际能藏的字节数**，不要再乘一遍。
（我第一版验证脚本里乘了两遍，得出「512×512 只能藏 42 字节」，是错的。）

实测可用容量（合成纹理图，已含 5% 上限）：

| 尺寸 | 质量 90 | 质量 75 |
| --- | --- | --- |
| 512×512 | **852 字节** | 356 字节 |
| 1024×768 | 2812 字节 | 1280 字节 |
| 1920×1080 | **7772 字节** | 3708 字节 |
| 3840×2160 | **31788 字节** | 15420 字节 |

**对演示的直接影响**：一条 300 字中文短信约 900 字节。
→ 用 512×512 的图**刚好卡在线上**，用 1920×1080 才舒服。
→ 计划 §7 里「5% 上限太小」这条风险现在有了量化答案：**默认演示载体至少 1920×1080，且纹理越复杂容量越大。**
→ 另注：JPEG 质量越高容量越大（高质量图非零 DCT 系数更多）。演示用 q=90 比 q=75 容量高一倍。

### 6.2 错误口令会「静默失败」——这是 GUI 必须堵的洞

```python
try:
    ...
except Exception:
    print("WARNING: message not found")   # 只打一行字
    plain = bytearray()                    # 然后写出一个 0 字节文件
```

实测：用错误口令调 `extract()`，**不抛任何异常**，只往 stderr 打一行 WARNING，
然后**正常写出一个 0 字节的输出文件**。

→ 你的 MVP 第 10 项（异常场景友好提示）不能靠 try/except 捕获，
必须**自己判断输出文件是否为空**，否则用户会以为"提取成功但内容是空的"。
这是 GUI 封装 `HStegoEngine` 时必须加的一层。

---

## 七、下一步

| 优先级 | 事项 |
| --- | --- |
| 高 | 计划 §4 / §7 已更新：JPEG Toolbox 从「未通过」改为「已通过」，风险条目标记关闭 |
| 高 | GUI 封装 `HStegoEngine` 时加上「输出为空 = 口令错误」的判定 |
| 中 | 演示载体默认选 1920×1080 以上、高纹理、q=90 的图 |
| 中 | 把 §5 的 DCT 改动统计（±1 / 0.09% / PSNR 64.5dB）做成 UI 上的"安全指标卡" |
| 低 | 官方 exe `hstego-0.6.1-win.amd64.exe` 可下下来做功能对照，验证自建版结果一致 |

**阻塞解除。Day 5 的任务完成了，可以按计划进 Day 6（PNG 藏取 + 读 UNIWARD/STC 原文的框图）。**
