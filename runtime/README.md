# runtime/ — 预编译的原生扩展

## 这两个文件是什么

hstego 的核心算法**不在 Python 里**，而在两个 C/C++ 原生扩展里：

| 文件 | 大小 | 是什么 |
| --- | --- | --- |
| `hstego_stc_extension.so` | 58 KB | **STC 编码器**（C++）。给定代价图 + 消息，用维特比算法找出总失真最小的嵌入位置 |
| `hstego_jpeg_toolbox_extension.so` | 109 KB | **JPEG 系数读写**（C）。直接读写 DCT 系数、量化表，是 J-UNIWARD 的前提 |

`hstegolib.py` 用 `ctypes.CDLL` 加载它们，匹配名 `hstego_<name>_extension*.so|pyd|dll`，
搜索目录 = `hstegolib.py` 所在目录 + `build/lib.*`。
**所以把这两个文件放到 `hstegolib.py` 同目录即可生效**（`setup.bat` 就是这么做的）。

## 为什么把编译产物放进仓库

上游仓库不跟踪 `.so`（正常的做法——它们是构建产物）。但在这台机器上重新构建**相当麻烦**：

- 官方 `setup.py` 定位 Visual Studio 失败（本机 `reg.exe` 被黑名单拦截）；
- 仓库自带的 `src/jpeg-9c-win/Lib/static_x64/jpeg.lib` 带 `/DEFAULTLIB:libucrt` 静态 UCRT 指令，
  与导入版 ucrt 冲突 → `LNK2005` 多重定义 → `LNK1169`。

我们绕过的办法（**不用那个 `.lib`，改用仓库自带的 libjpeg 完整源码**）写在
[`notes/经验_hstego原生扩展编译.md`](../notes/经验_hstego原生扩展编译.md)，
脚本是 [`tools/build_jpeg_toolbox.py`](../tools/build_jpeg_toolbox.py)。

**结论：带上这两个 170 KB 的产物，换台机器克隆下来就能直接跑，不必重编译。**

## 校验

仓库里这两个文件的 sha256（本机 MSVC 14.51 / Windows SDK 10.0.26100.0 / Python 3.13 编出）：

```
hstego_stc_extension.so            2e08d5290b80a13e51435bdf4408c67af98a68d90d29917c7646d776e6e3de7b
hstego_jpeg_toolbox_extension.so   5b0b46d233d4bb927dbd7a830e6bfea6acaf6ab009ec6a414770a2ddb25fbf05
```

自检（`setup.bat` 最后一步会自动跑）：

```bat
hstego-runtime\.venv\Scripts\python.exe -c "import ctypes; ctypes.CDLL(r'...\hstego_stc_extension.so'); ctypes.CDLL(r'...\hstego_jpeg_toolbox_extension.so'); print('OK')"
```

> ⚠️ 这两个扩展是在 **Python 3.13 x64** 上编的，依赖 `python313.dll`。
> 换 Python 版本（3.11/3.12）**必须重新编译**，
> 用 `tools/build_jpeg_toolbox.py` 改一下产出的 `.lib` 名即可。

## `requirements-hstego.txt`

算法层的完整依赖清单（numpy / scipy / pillow / pycryptodome / numba / imageio / pypdf）。
Web 层多出来的依赖在 [`webapp/requirements.txt`](../webapp/requirements.txt)。
