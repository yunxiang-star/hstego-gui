# 项目名称

> 一句话说明这个仓库是做什么的。

<!-- TODO: 把上面的标题和这句话换成你自己的项目 -->

## 项目简介

<!-- TODO: 3-5 行说清楚：解决什么问题、用到什么方法、当前进度 -->

- **目标**：
- **方法**：
- **当前状态**：开发中

## 环境准备

```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 激活（Windows Git Bash）
source .venv/Scripts/activate

# 3. 安装依赖
pip install -r requirements.txt
```

> 还没有 `requirements.txt`？等代码写起来后用它冻结依赖：
> `pip freeze > requirements.txt`

## 目录结构

```
.
├── README.md
├── .gitignore
├── src/            # 源代码（待建）
├── data/           # 数据集，不入库
└── outputs/        # 运行产物，不入库
```

## 使用方式

```bash
# TODO: 补上运行命令
python src/main.py
```

## 备注

- `data/`、`outputs/`、模型权重等体积大的内容已在 `.gitignore` 中排除。
- 密钥、令牌等敏感信息请放 `.env`，同样不入库。
