# 项目全景说明：从输入问题到生成报告

这份文档是整个项目的“地图”。第一次学习时，先读本文件，再看代码。

## 1. 系统是什么

这是一个可以在本机运行、也能通过 Docker 交付给其他电脑的多 Agent 论文调研系统。
用户输入研究问题和英文检索词后，系统自动检索论文、去重、初筛、研读、核验证据，
最后生成 Markdown 报告。

系统没有让多个模型随意聊天。它采用“程序控制流程，模型负责判断”的设计：

```text
浏览器/命令行
    ↓
LangGraph 顶层工作流（阶段顺序 + 大阶段断点）
    ↓
自研 HarnessRuntime（论文队列 + 并发池 + 租约 + 重试）
    ↓
Screener / Reader / Verifier / Synthesizer 四个 Agent
    ↓
Pydantic 数据校验 + QualityGate 质量闸门
    ↓
SQLite 持久化 + Markdown 报告
```

## 2. 一次任务的完整过程

1. 用户在 Gradio 网页填写 DeepSeek Key、问题、检索词、年份和论文数。
2. UI 在后台线程创建任务，避免浏览器请求一直卡住。
3. `ResearchWorkflow` 创建 `run_id`，并把任务写入 `research.db`。
4. `search` 节点调用 OpenAlex 和 Crossref，随后按 DOI/标题去重。
5. `screen` 节点让 Screener 判断 include、exclude 或 review。
6. 对入选论文尝试取得合法开放全文；也可以使用用户上传的 PDF。
7. HarnessRuntime 把每篇论文放进 SQLite 工作队列。
8. 多个 Worker 并发执行 Reader 和 Verifier；失败任务按配置重试。
9. QualityGate 用代码规则决定研究卡能否进入最终综合。
10. Synthesizer 只读取通过核验的研究卡，输出结构化报告对象。
11. 程序把对象渲染成 Markdown，保存到 `data/reports/<run_id>.md`。

## 3. Harness 是什么

Agent 类似专业员工；Harness 是让员工可靠协作的工作制度和运行底座。本项目的
Harness 由两部分组成：

- LangGraph：管理 `search → screen → read_and_verify → synthesize` 的顶层状态图，
  并用 checkpoint 记录执行到哪个节点。
- 自研 `HarnessRuntime`：管理逐篇论文的 SQLite 队列、有限并发 Worker、任务租约、
  失败重试、过期租约恢复和质量闸门。

为什么不只用 LangGraph：LangGraph 很适合描述大阶段，但本项目还需要论文级任务
队列、租约和产品统计，因此保留了一层很小的领域 Runtime。

## 4. 当前到底有几个 Agent

当前代码中有 **4 个真正调用大模型的 Agent**：

| Agent | 输入 | 输出 | 职责边界 |
|---|---|---|---|
| Screener | 问题和候选元数据 | 筛选决定 | 判断是否相关，不写最终结论 |
| Reader | 摘要或全文 | ResearchCard | 提取方法、实验、结论和定位证据 |
| Verifier | 原文和 ResearchCard | VerificationReport | 独立逐条核验证据 |
| Synthesizer | 通过核验的卡片 | SynthesisReport | 跨论文综合和产品建议 |

OpenAlex/Crossref 是检索工具，不是 Agent；LangGraph/HarnessRuntime 是编排系统，
也不是 Agent。README 中的 query planner、product analyst 是后续可扩展角色，当前
没有作为独立模型 Agent 实现，不能计入现有数量。

## 5. 有没有 Skill

当前项目 **没有独立的 Skill 插件系统或 `SKILL.md`**。现有 Agent 能力直接写在
Python 类、system prompt、工具函数和 Pydantic Schema 中。

这里要区分：

- Tool：确定性函数，例如检索 OpenAlex、解析 PDF、去重。
- Skill：可复用的能力包，通常包含说明、流程、工具约束和模板。
- Agent：使用模型做语义判断的执行角色。
- Harness：调度 Agent/Tool、保存状态、重试和把关的基础设施。

如果以后要做跨项目复用，可以把“系统综述检索策略”“证据核验规范”等拆成 Skill；
本周交付版本不需要为了概念完整而额外引入 Skill 框架。

## 6. 为什么重新打开不会丢状态

状态不是只放在 Python 内存里，而是写到 `data` 目录：

- `research.db`：任务、候选论文、研究卡、核验结果、工作队列、重试次数。
- `research_langgraph_checkpoints.db`：LangGraph 节点和状态检查点。
- `reports/`：最终 Markdown 报告。
- `uploads/`：用户上传的 PDF（产生后出现）。

Docker Compose 使用 `./data:/app/data` 把本机目录挂载进容器。删除或重建容器不会
删除本机 `data`。任务中断后，用页面中的 run_id 或命令 `paper-agents resume-run
<run_id>` 恢复。要真正防止硬盘损坏，还应定期备份整个 `data` 文件夹。

## 7. 开发一个 Agent 需要什么

最少需要以下条件：

1. 明确、单一的职责，例如“逐条核验证据”，而不是“帮我研究所有内容”。
2. 明确输入输出契约；本项目使用 Pydantic Schema，避免 Agent 之间传散乱文字。
3. 一个模型 Provider；本项目通过 OpenAI-compatible HTTP 接口调用 DeepSeek。
4. Prompt 和边界规则，明确何时必须承认信息不足。
5. 必要工具，例如检索 API、PDF 解析、数据库。
6. Harness 支持，包括调度、并发、超时、重试、日志和状态保存。
7. 质量评估，包括字段校验、证据核验、自动测试和人工抽查。
8. 部署环境，包括 Python 或 Docker、网络、API Key、CPU/内存和持久化磁盘。

新增 Agent 的推荐步骤：先在 `schemas.py` 定义输出，再在 `agents/` 写类和 Prompt，
然后把节点接入 `workflow.py`，最后为正常、无信息、模型格式错误和中断恢复写测试。

## 8. 文件和文件夹地图

| 路径 | 作用 |
|---|---|
| `README.md` | 项目首页和最短启动说明 |
| `Dockerfile` | 定义容器里安装什么、启动什么 |
| `docker-compose.yml` | 端口、数据挂载、重启策略 |
| `pyproject.toml` | Python 包、依赖和命令入口 |
| `requirements.txt` | 兼容传统 pip 的依赖入口 |
| `.env.example` | 环境变量示例；复制后再填自己的 Key |
| `start_mac.command` | macOS 本地 Python 一键启动 |
| `start_windows.bat` | Windows 本地 Python 一键启动 |
| `src/` | 正式产品源码 |
| `tests/` | 自动测试，防止修改后破坏原功能 |
| `config/` | 研究主题和业务配置 |
| `docs/` | 产品、架构、部署和数据契约文档 |
| `examples/` | 可用于学习和测试的示例输入输出 |
| `data/` | 持久化运行数据；部署时必须保留 |
| `scripts/` | 制作安全交付包的维护脚本 |
| `artifact.md`、`build_weekly_report.py`、`add_paper_reading_to_weekly_report.py` | 项目早期周报辅助材料，不参与当前 Web 工作流 |

`.venv/`、`__pycache__/`、`*.egg-info/` 是本机生成物，不是源代码，也不应放进交付包。

## 9. 如何部署到另一台电脑

推荐 Docker，因为它把 Python 和依赖版本一起封装：

1. 把 `dist/论文调研多Agent系统-v0.1.0.zip` 发给对方。
2. 对方安装 Docker Desktop并启动它。
3. 解压压缩包，打开终端并进入解压后的项目目录。
4. 运行 `docker compose up --build -d`。
5. 浏览器打开 `http://127.0.0.1:7860`。
6. 在网页填写对方自己的 DeepSeek API Key，不要把你的 `.env` 发出去。

更新代码后重新执行 `docker compose up --build -d`。停止使用执行
`docker compose down`；这不会删除 `data`。不要执行 `docker compose down -v`，
也不要手工删除 `data`，除非确定不需要历史任务。

## 10. 本地部署与 Docker 部署的区别

- 本地 Python：代码直接在电脑上运行，需要 Python 3.11+ 和虚拟环境，便于开发。
- Docker：代码在容器中运行，只要求 Docker，最适合交付和演示。
- 两者的网页和业务流程相同；不要同时占用 7860 端口。

