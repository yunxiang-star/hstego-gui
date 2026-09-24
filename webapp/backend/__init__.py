"""HStego Web 后端。

分层：
    backend.engine   —— 隐写引擎抽象层（StegoEngine / HStegoEngine）
    backend.jobs     —— 作业调度（线程池 + 阶段进度 + 日志）
    backend.storage  —— 产物存储（token 化下载）
    backend.app      —— FastAPI 路由

设计约束来自课题第一章的实测结论：
1. hstegolib 的 extract() 失败时不抛异常，只往 stdout 打 WARNING 并写出 0 字节文件
   → 判定必须靠"输出为空 / sha256 不符"，不能靠 try/except。
2. hstegolib 用模块级 random.seed()/shuffle() 选嵌入位置
   → 引擎调用必须全局串行，否则并发嵌入会互相污染。
3. jpg_capacity() 返回的是密文预算，不是原始载荷上限
   → 容量口径必须用 60 + len(zlib.compress(data, 9)) 实际算。
"""

__version__ = "0.1.0"
