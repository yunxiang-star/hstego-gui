---
name: hstego-windows-native-build
description: >
  hstego 在本机的编译与应用层全套经验。编译侧：手工用 MSVC 编两个原生扩展（STC 引擎与
  JPEG Toolbox），适用于「hstego 源码装不上 / import hstegolib 报 JPEG Toolbox library
  not found / LNK2005 LNK1169 CRT 冲突」以及重新出 .so 产物的场合。应用侧：hstego 的 API
  陷阱——J-UNIWARD 提取静默失败（约 25%）、容量口径（密文预算 vs 原始字节）、错误口令与
  提取失败症状相同、必须做嵌入后自检。关键词：hstego、jpeg toolbox、
  jpeg_toolbox_extension、stc_extension、libjpeg、LNK1169、LNK2005、D9002、MSVC 手工编译、
  UNIWARD、STC、隐写、steganography、jpg_capacity、message not found。
agent_created: true
---

# 编译 hstego 原生扩展（Windows / MSVC 手工路线）

## 何时用

- `import hstegolib` 报 `RuntimeError: JPEG Toolbox library not found` 或 `STC library not found`
- `pip install hstego` / `setup.py build` 卡在定位 Visual Studio（本机 `reg.exe` 被黑名单拦截）
- 链接报 `LNK2005` / `LNK1169` / `LNK2019`
- 换了 Python 版本、要重新产出 `.so`

## 铁律（踩过坑的结论，别绕）

1. **绝不链接仓库自带的 `src/jpeg-9c-win/Lib/static_x64/jpeg.lib`。**
   它是别人用 MSVC 2017 编的，obj 里带着 `/DEFAULTLIB:libucrt`（静态 UCRT）指令，
   与你自己的构建（导入版 ucrt）冲突 → `LNK2005 多重定义` → `LNK1169`。
2. **改用仓库自带的 libjpeg 9c 完整源码**（`src/jpeg-9c-win/jpeg-9c-src/`，46 个库源文件一个不缺），
   和 `src/jpeg_toolbox_extension.c` **在同一次 `cl` 调用里一起编**。
   全工程只有一套编译器 + 一套 CRT，冲突在物理上不可能发生。**3 秒编完，无需联网。**
3. **编译必须加 `/MD`**（动态 UCRT），与 CPython 一致。
4. **链接器参数必须写在 `/link` 之后。** `cl` 会把 `/NODEFAULTLIB:xxx` 这类参数
   当未知选项**静默丢弃**并只给 `warning D9002`。看到 D9002 必须当 error 处理——
   否则你的"修复"一行都没生效。
5. **JPEG 扩展必须显式链 `python313.lib`**（源码里没有 `#pragma comment(lib,...)`，
   但它用了 `PyDict_New` 等 C-API）。
   对比：STC 扩展是纯 C++、不碰 Python C-API，所以它不需要——这也解释了
   为什么会出现"STC 编得过、JPEG 编不过"，**工具链一直是好的**。
6. **`jconfig.h` 是唯一缺的文件**，从 `src/jpeg-9c-win/Include/jconfig.h` 拷一份即可。
   （已验证它与 `jpeg-9c-src/jconfig.vc` 逐行相同。）

## 环境事实（本机）

| 项 | 值 |
| --- | --- |
| MSVC | `C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.51.36231` |
| cl.exe | `<MSVC>\bin\Hostx64\x64\cl.exe` |
| Windows SDK | `10.0.26100.0`（`C:\Program Files (x86)\Windows Kits\10`） |
| Python | `C:\Users\ILLENIUM\.workbuddy\binaries\python\versions\3.13.12` |
| venv | `C:\Users\ILLENIUM\.workbuddy\binaries\python\envs\default\Scripts\python.exe` |
| 源码 | `C:\Users\ILLENIUM\WorkBuddy\2026-09-20-17-02-48\hstego-src` |

## 执行

```bash
cd "C:/Users/ILLENIUM/WorkBuddy/2026-09-20-17-02-48"
"C:/Users/ILLENIUM/.workbuddy/binaries/python/envs/default/Scripts/python.exe" build_jpeg_toolbox.py
"C:/Users/ILLENIUM/.workbuddy/binaries/python/envs/default/Scripts/python.exe" test_jpeg_toolbox.py
```

`build_jpeg_toolbox.py` 自带工具链自动定位（glob 找 MSVC / SDK，不依赖 setuptools、不碰 reg.exe），
产出 `hstego-src/hstego_jpeg_toolbox_extension.so`。

## 关键命令模板

```bat
cl /nologo /LD /O2 /MD /D _CRT_SECURE_NO_WARNINGS ^
   /I <jpeg-9c-src> /I <jpeg-9c-win\Include> /I <builddir> /I <Python>\include ^
   src\jpeg_toolbox_extension.c <46 个 libjpeg .c> ^
   /link /OUT:<out>.so /INCREMENTAL:NO python313.lib
```

libjpeg 库本体需要这 46 个源文件（排除 cjpeg/djpeg/jpegtran/rd*/wr*/jmemansi/jmemdos/jmemmac/jmemname）：
`jcapimin jcapistd jcarith jccoefct jccolor jcdctmgr jchuff jcinit jcmainct jcmarker jcmaster jcomapi jcparam jcprepct jcsample jctrans jdapimin jdapistd jdarith jdatadst jdatasrc jdcoefct jdcolor jddctmgr jdhuff jdinput jdmainct jdmarker jdmaster jdmerge jdpostct jdsample jdtrans jerror jfdctflt jfdctfst jfdctint jidctflt jidctfst jidctint jmemmgr jmemnobs jquant1 jquant2 jutils jaricom`

## 验证要点（别只看 import 成功）

`hstegolib.py` 用 `ctypes.CDLL` 加载，加载名匹配 `hstego_<name>_extension*.so|pyd|dll`，
搜索目录 = `hstegolib.py` 所在目录 + `build/lib.*`。**产物放源码根目录即可。**

要真跑通才算数：

1. `CDLL(path)` 直接加载，确认导出符号 `read_file` / `write_file`
2. `lib.read_file(path)` 返回 dict，含 `coef_arrays`（Y 通道 `(块行, 块列, 8, 8)`）与 `quant_tables`
3. **J-UNIWARD 藏取往返 sha256 一致**（⚠️ 必须真跑提取，`embed()` 返回不代表能取回，见下）
4. 改动幅度应仅 ±1（最小失真的特征，可作答辩论据）

---

## ⚠️ 应用层四个已验证的陷阱（2026-09-23 实测，全部推翻了早期结论）

### 1. JPEG 域提取失败率 25%，且完全静默

USC-SIPI 9 张标准图 × 128B 真随机载荷：空间域 **9/9** 通过，压缩域 **6/8** 通过。
失败与容量无关（sailboat 容量 972B、只藏 128B 仍失败），**无法从载体尺寸/容量/纹理预测**，
载荷本身也能触发（airplane 换载荷就从成功变失败）。

**`extract()` 失败时不抛异常**，只 `print("WARNING: message not found")` 到 **stdout**
（不是 stderr！），然后正常写出 **0 字节文件**。

→ 调用方**必须**：① 嵌入后立刻自己提取一次并校验 sha256；
② 用「输出不存在 / 0 字节 / hash 不符」判失败，**不能靠 try/except**；
③ 失败重试要换编码质量（实测对失败载体 q95 有效），序列 `q95 → q92 → q88 → 换载体`。

失败的真实环节是**通道 0 前 512 个位置里的 32 字节头部**（`HEADER_COVER_LEN = 32×8×2`），
`decrypt_header()` 抛 `MAC check failed`，被 `extract()` 的 `except` 吞掉。

### 2. `jpg_capacity()` 是「密文预算」，不是「能藏多少原始字节」

**不要**再乘 5%（这点早期是对的），但**也不要**当成原始载荷上限。卡的是加密后的长度：

```
密文长度 = 60 + len(zlib.compress(载荷, 9))
             └ salt16 + nonce16 + tag16 + magic4 + len8 = 60 固定开销
             └ AES-EAX 是流式模式，不做块填充
可藏原始字节 ≈ jpg_capacity() - 71      # 不可压缩载荷
```

可压缩载荷（纯文本）能藏更多。所以 UI 必须**按用户实际上传的文件**算，只报一个容量数字会撞
`ValueError: Message too long: {密文} > {capacity}`。

### 3. 容量不能用尺寸估算（早期那组数字是错的）

⚠️ **已作废**：早期记录的「512×512→852B、1920×1080→7772B、3840×2160→31788B」是用
`rng.normal(0, 9)` 生成的**合成噪声图**测的——高斯噪声造出海量非零 DCT 系数，数字系统性虚高。

真实照片（512×512, q90, 4:4:4）：`splash` 仅 **460B**，`baboon` **1532B**，`airplane` 508B，
`sailboat` 972B，`peppers` 700B，`barbara` 516B —— **同尺寸差 3.3 倍，容量由纹理决定**。

### 4. 错误口令 / 提取失败 / 图中无消息，三者症状完全相同

都表现为「0 字节输出 + 一行 stdout WARNING」，**无法区分**。UI 文案不要断言"口令错误"。

---

## 应用层还有两条（详见技能 `hstego-webapp-backend`）

5. **`hstegolib` 不是线程安全的**：`Stego.hide*` / `unhide*` 用**模块级**
   `random.seed(password_seed)` + `random.shuffle(indices)` 选嵌入位置。
   任何封装（Web 服务 / GUI 后台线程）都必须用一把全局锁把所有原生调用串起来，
   否则并发嵌入会互相污染。`redirect_stdout` 捕获 WARNING 同样要在锁内做。
6. **重试有效是"扰动"不是"容量"**：把已量化过的 DCT 系数用更细量化表再量化一次
   （double quantization）等价于换载体。实测 sailboat q90 → q95 **容量不变（972 B）**，
   但自检从 `empty_output` 变成通过。别讲成"质量高所以容量大"。

现成实现（自检 + 重试 + 容量口径 + PSNR/SSIM + 差分图 + FastAPI）：
`D:\projects\hstego\webapp\`

---

## 实测基线（可直接引用的参考值）

| 域 | 往返一致 | PSNR | SSIM | 嵌入耗时 |
| --- | --- | --- | --- | --- |
| 空间域 PNG / S-UNIWARD | 9/9 | 均值 79.52 dB（72.08–83.41） | > 0.999984 | 5.5–7.7 s |
| 压缩域 JPEG / J-UNIWARD | 6/8 | 均值 61.27 dB（58.24–62.99） | > 0.999699 | 6–17 s |

（载荷 128B 真随机 + 口令 `baseline-pwd-2026`，scrypt n=2^18 是主要耗时来源）

