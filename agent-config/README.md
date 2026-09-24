# agent-config/ — 给 AI 编程助手用的项目说明书

把这三样东西拷到项目根目录，AI 助手（[opencode](https://opencode.ai)）就变成"懂这个课题"的助手：

```
AGENTS.md          →  项目根/AGENTS.md          每次对话自动加载的项目说明书
opencode.jsonc     →  项目根/opencode.jsonc     权限与模型配置（默认"改动先问"）
.opencode/         →  项目根/.opencode/         两个子智能体定义
```

## 两个子智能体

| 文件 | 角色 | 权限 |
| --- | --- | --- |
| `.opencode/agents/stego-dev.md` | **工程实现助手**。改代码、接 hstego 的 API、调试报错、搭界面。规矩是「小步走，每步可验证」+「改之前先说明改哪个文件/改什么/为什么/怎么验证」 | 可改文件（先问） |
| `.opencode/agents/stego-tutor.md` | **理论助教**。解释 UNIWARD/STC/失真函数/嵌入率，划定论文阅读范围。核心规矩是**先回答「这个知识点需要掌握到什么程度」**（必须懂 / 知道名词 / 可以直接跳过） | 只读 |

`stego-tutor` 的第一原则值得单独记下来：

> 用户最大的问题不是"学不会"，而是**不知道该学多少**，
> 容易陷入"先读完所有论文再动手"的陷阱。
> 所以每次回答理论问题，**必须先回答「他需要掌握到什么程度」**。

## 配置要点

- 模型走 `deepseek/deepseek-v4-pro`；
- `edit: "ask"`、`bash: "*": "ask"` —— 默认不自动改文件；
  只读命令（`git status` / `git diff` / `git log` / `ls` / `python --version`）直接放行；
- `webfetch: "allow"` —— 允许联网查论文和库文档。

`使用说明.md` 里有完整的安装与使用步骤（含 opencode 本体、VSCode 扩展、凭据存放位置）。
