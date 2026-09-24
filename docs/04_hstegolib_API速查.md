# hstegolib API 速查

> 照 `hstegolib.py` 源码核对（v0.6.1）。**这几个签名最容易被记错，写反了报错很难懂。**

## 两个引擎类

```python
import hstegolib

s = hstegolib.S_UNIWARD()   # 空间域 S-UNIWARD（PNG / BMP / TIFF 等位图载体）
j = hstegolib.J_UNIWARD()   # 压缩域 J-UNIWARD（JPEG 载体，含代价极化）
```

## 嵌入 / 提取

```python
.embed(input_img_path, msg_file_path, password, output_img_path)
        ↑ 载体在前       ↑ 消息在后     ↑ 口令第三   ↑ 输出最后
```

> ⚠️ **参数顺序写反的典型报错**：
> `PIL.UnidentifiedImageError: cannot identify image file 'msg.txt'`
> —— 因为 `input_img_path` 位置收到了消息文件，它会被拿去 `Image.open()` 当图打开。

```python
.extract(stego_img_path, password, output_msg_path)
```

> ⚠️ **提取失败不抛异常**。只 `print("WARNING: message not found")` 到 **stdout**，
> 然后正常写出 **0 字节**结果文件。判失败只能靠产物，见
> [`../notes/经验_hstego应用层封装.md`](../notes/经验_hstego应用层封装.md)。

## 容量 —— 是模块级函数，不是类方法

```python
hstegolib.spatial_capacity(img_array)      # 空间域，返回字节数
hstegolib.jpg_capacity(jpg_path)           # 压缩域，返回字节数
hstegolib.spatial_channel_capacity(ch)     # 单通道
hstegolib.jpg_channel_capacity(coef_array) # 单通道
```

> ⚠️ `S_UNIWARD` / `J_UNIWARD` 上**只有** `cost_fn`、`embed`、`extract`
> （`J_UNIWARD` 多一个 `cost_polarization`）。
> 写 `s.capacity()` 会得到 `AttributeError: 'S_UNIWARD' object has no attribute 'capacity'`。

> ⚠️ 两个 `*_capacity()` 返回的都是**密文预算**（内部已含 5% 安全上限），
> **不是**"能藏多少原始字节"。密文长度 = `60 + len(zlib.compress(载荷, 9))`。
> 可压缩载荷（纯文本）能藏得更多。详见 `notes/经验_hstego应用层封装.md` 第 3 条。

## 一个可运行的最小示例

```python
import os, tempfile
import hstegolib
from PIL import Image
import numpy as np

tmp = tempfile.mkdtemp()
cover = os.path.join(tmp, 'cover.png')
stego = os.path.join(tmp, 'stego.png')
out   = os.path.join(tmp, 'out.bin')
msg   = os.path.join(tmp, 'msg.bin')

rng = np.random.default_rng(7)
Image.fromarray(rng.integers(0, 255, (512, 512), dtype=np.uint8)).save(cover)
open(msg, 'wb').write(os.urandom(64))

hstegolib.S_UNIWARD().embed(cover, msg, 'demo-pwd-2026', stego)
hstegolib.S_UNIWARD().extract(stego, 'demo-pwd-2026', out)

ok = os.path.getsize(out) > 0 and open(out, 'rb').read() == open(msg, 'rb').read()
print('往返', 'PASS' if ok else 'FAIL')
```

输出：`往返 PASS`。已在本仓库的 `runtime/*.so` 上实测通过（空间域与压缩域都通过）。

## 域不能混

`.png` 走 S-UNIWARD、`.jpg` 走 J-UNIWARD，**两者不通用**——
隐写和提取必须落在**同一个域**。判域看**文件内容**而不是后缀（hstego 自己就是这么做的）。

## 其他有用的事实

| 项 | 值 |
| --- | --- |
| 单次嵌入耗时 | 空间域 5.5–7.7 s；压缩域 6–17 s（scrypt n=2^18 是主要耗时来源，一次调用要派生 3 次） |
| 线程安全 | ❌ 用模块级 `random.seed()` + `random.shuffle()` 选嵌入位置，**必须全局串行** |
| 载荷上限 | `MAX_PAYLOAD = 0.05`（总容量的 5%）。超过这个嵌入率，深度学习隐写分析器能可靠检出 |
| 密文固定开销 | 60 字节（salt16 + nonce16 + tag16 + magic4 + len8），AES-EAX 是流式模式不做块填充 |
| 提取结果里 | **不含原始文件名**，只存内容 |
