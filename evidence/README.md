# evidence/ — 实测证据

答辩时最怕的是"你说得挺有道理，但拿什么证明"。这个目录就是证据。

## 一、评测基线

| 文件 | 内容 |
| --- | --- |
| `评测基线报告.md` | 9 张 USC-SIPI 标准图 × 空间域/压缩域完整数据表（容量、密文、PSNR、SSIM、改动像素比例、耗时、往返是否一致） |
| `评测基线原始数据.csv` | 上面那张表的机器可读版，方便二次统计与画图 |

复现方式：`tools/baseline_eval.py`，约 260 秒。

**关键结论**：空间域往返 **9/9**，压缩域往返 **6/8（失败率 25%）**。
失败的两条是 `sailboat`（容量 972 B，只藏 128 B）和 `airplane`（容量 508 B，只藏 128 B）
—— 都是**做了冗余设计仍然失败**，不是容量不够。

## 二、失败证据（`失败证据_JUNIWARD/`）

四条文件成对，**可以直接在答辩现场演示**：

| 文件 | 说明 |
| --- | --- |
| `sailboat_cover_q90.jpg` | 原始载体（USC-SIPI 标准图，q90/4:4:4） |
| `sailboat_stego_q90.jpg` | 嵌入 128 B 真随机载荷后的载密图（肉眼与载体无差别） |
| `sailboat_jpeg_secret.bin` | 128 字节真随机载荷（不可压缩） |
| `sailboat_jpeg_extracted.bin` | **提取结果 —— 0 字节。** 这就是缺陷的证据 |

`airplane` 一组同理。

> 用命令复现：
> ```bat
> hstego-runtime\.venv\Scripts\python.exe hstego.py extract ^
>     evidence\失败证据_JUNIWARD\sailboat_stego_q90.jpg ^
>     out.bin ^
>     baseline-pwd-2026
> ```
> 你会看到 stdout 上一行 `WARNING: message not found`，`out.bin` 被写成 0 字节，
> **退出码是 0（"成功"）**。这就是"静默失败"的完整现场。

## 三、诊断脚本

| 文件 | 用途 |
| --- | --- |
| `diag_head3.py` | 直插头部：定位失败环节在「通道 0 前 512 个嵌入位置里的 32 字节头部」 |
| `diag_retry.py` | 重试链路验证：换编码质量后同一载体能否通过 |
| `diag_sailboat2.py` | sailboat 专项复现（它对任何载荷都失败，是最稳的复现样本） |

## 四、构建日志

| 文件 | 内容 |
| --- | --- |
| `build_jpeg_log.txt` | 手工编译 JPEG Toolbox 扩展的完整 `cl` 输出 |
| `test_jpeg_log.txt` | 编译后验收测试的输出（加载、导出符号、往返 sha256） |

## 五、⚠️ 已作废的数据

`容量基准_合成噪声图_已作废.txt` —— 里面那组「512×512→852 B、1920×1080→7772 B」
按尺寸递增的数字，是用 `rng.normal(0, 9)` 生成的**合成高斯噪声图**测的。
噪声图有海量非零 DCT 系数，数字**系统性虚高**。

真实照片（512×512, q90, 4:4:4）实测：`splash` **460 B**、`baboon` **1532 B**、
`airplane` 508 B、`sailboat` 972 B、`peppers` 700 B、`barbara` 516 B
—— **同尺寸差 3.3 倍，容量由纹理决定，不能用尺寸估算。**

留着这份文件是为了说明"我们推翻过自己早期的结论"，这本身也是过程证据。
