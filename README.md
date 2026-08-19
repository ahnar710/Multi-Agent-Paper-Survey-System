# 论文调研多 Agent 系统

面向产品和技术决策的可追溯文献调研系统。GNSS 多径研究是第一个示例主题。

第一次阅读项目，请先看 [项目全景说明](docs/PROJECT_MAP.md)。它逐步解释完整流程、
架构、每个目录、4 个 Agent、Harness、状态恢复和跨电脑部署。

系统使用“确定性工作流 + 专家 Agent”的 Harness：LangGraph 负责检索、筛选、
研读核验和报告生成的大流程，项目自己的 SQLite Runtime 负责逐篇论文队列、
并发 Worker、租约、重试和质量闸门。Agent 负责需要语义判断的任务。

LangGraph checkpoint 保存在研究数据库旁边的
`*_langgraph_checkpoints.db` 文件中，程序重启后可以从未完成节点继续。

## 当前进度

- [x] 研究卡片、证据和任务状态的 Pydantic 数据契约
- [x] 示例研究卡片和自动校验测试
- [x] 统一模型 Provider 和 Reader Agent（含校验重试）
- [x] OpenAlex + Crossref 多源检索、开放获取 PDF 与 DOI/标题去重
- [x] SQLite 任务状态和 Verifier Agent
- [x] 一键工作流和中断恢复
- [x] Synthesizer 结构化综合和 Markdown 报告
- [x] Gradio 本地网页界面和后台任务
- [x] LangGraph 顶层编排和 SQLite checkpoint 恢复
- [x] 用户 PDF 上传、分页文本提取与全文级证据定位
- [x] Docker 和 Windows/macOS 跨电脑部署文件

## 开发者快速验证

需要 Python 3.11 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
paper-agents validate-card examples/research_card.example.json
PYTHONPATH=src python -m unittest discover -s tests -v
```

Windows PowerShell 激活虚拟环境使用：

```powershell
.venv\Scripts\Activate.ps1
```

## 运行 Reader Agent

1. 复制环境变量模板：

```bash
cp .env.example .env
```

2. 在 `.env` 中填写自己的 DeepSeek API Key。模板已默认配置为：

```dotenv
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=你的-DeepSeek-API-Key
LLM_MODEL=deepseek-v4-flash
LLM_MAX_TOKENS=12000
```

Reader 默认使用 `deepseek-v4-flash`。更复杂但成本更高的任务可改为 `deepseek-v4-pro`。不要将 `.env` 发给别人或提交到 Git。

3. 研读示例输入：

```bash
paper-agents read-paper examples/paper_document.example.json \
  --output data/cards/example-001.json
```

Reader Agent 会将模型输出解析为 `ResearchCard`。如果第一次输出不合格，它会将校验错误返回给模型修正一次。

## 最简单的启动方式

- macOS：双击 `start_mac.command`
- Windows（推荐 Docker）：双击 `start_windows_docker.bat`
- Windows（已安装 Python 3.11+）：双击 `start_windows.bat`
- Docker：运行 `docker compose up --build`

打开 `http://127.0.0.1:7860`，在网页内填写 DeepSeek API Key。详细操作、
架构和演示话术见 [产品使用与讲解手册](docs/PRODUCT_GUIDE.md)。

## 检索和初筛

Crossref 公共 REST API 不需要 API Key。建议在 `.env` 中将 `CROSSREF_MAILTO` 改为自己的邮箱，以使用 Crossref polite pool。

```bash
paper-agents search-crossref "GNSS multipath mitigation urban canyon" \
  --rows 10 --from-year 2021 --until-year 2026 \
  --output data/candidates/gnss-multipath.json

paper-agents screen-candidates \
  data/candidates/gnss-multipath.json \
  "近五年 GNSS 多径与 NLOS 检测、建模和抑制方法，以及它们的产品化潜力" \
  --output data/screening/gnss-multipath.json
```

## 任务状态和独立核验

```bash
paper-agents create-run gnss-multipath "近五年 GNSS 多径与 NLOS 技术"
paper-agents list-runs

paper-agents verify-paper \
  examples/paper_document.example.json \
  data/cards/example-001.json \
  --report-output data/verifications/example-001.json \
  --card-output data/cards/example-001.verified.json
```

SQLite 默认保存在 `data/research.db`。Verifier 只输出逐条核验结果，最终 `passed/failed` 由程序根据所有证据项计算。

## 一键调研工作流

```bash
paper-agents research \
  "近五年 GNSS 多径检测、建模和抑制方法有哪些？" \
  --query "GNSS multipath mitigation urban canyon" \
  --topic-id gnss-multipath \
  --rows 5 --from-year 2021 --until-year 2026
```

如果程序或网络中断，使用结果中的 `run_id` 继续：

```bash
paper-agents resume-run run-xxxxxxxxxxxx
```

恢复时会跳过已保存的检索、筛选和研读结果，只执行尚未完成的阶段。
最终报告保存在 `data/reports/<run_id>.md`。报告只使用 `verification_status=passed` 的研究卡片，并保留 paper ID 和 DOI。

## 本地网页界面

```bash
python -m pip install -e ".[ui]"
paper-agents-ui
```

默认打开 `http://127.0.0.1:7860`。用户在页面填写自己的 DeepSeek API Key，Key 只保留在当前本机进程内存，不写入 SQLite。调研工作在后台线程中继续，浏览器页签关闭不会主动取消任务；程序重启后可使用 `run_id` 恢复。

## 业务目标

- 每天完成 100 篇候选文献的高质量、可追溯研读
- 输出单篇结构化研究卡片、主题聚类、证据链和每日综述
- 支持产品决策，而不只是生成论文摘要

## 第一阶段：冻结验收口径

系统中的“一篇已研读文献”必须同时满足：

1. 唯一标识已解析（DOI、arXiv ID 或稳定来源 URL）
2. 元数据完整（标题、作者、年份、来源）
3. 已取得全文，或明确标记只能进行摘要级分析
4. 研究卡片通过字段完整性校验
5. 核心结论至少关联一个原文页码或章节定位
6. 质量评分达到阈值，且不存在重复文献

只有通过以上校验的记录才计入每日 100 篇产量。摘要级分析与失败记录单独统计。

## 正式工作流

```text
需求定义 -> 多源检索 -> 去重/初筛 -> 全文获取 -> 并行深读
        -> 引用与事实验证 -> 主题综合 -> 产品经理日报
```

## 初始 Agent 分工

- `orchestrator`：拆解任务、调度、重试、状态管理和预算控制
- `query_planner`：把产品问题转换为检索式和主题配额
- `retriever`：从学术数据源获取候选文献与元数据
- `screener`：相关性、质量、新颖性评分及去重
- `reader`：阅读全文并生成结构化研究卡片；以 Worker Pool 横向扩容
- `verifier`：核查原文定位、数值、引用和结论强度
- `synthesizer`：跨论文聚类、比较、冲突识别和趋势归纳
- `product_analyst`：将技术证据转为产品机会、风险与行动建议

## 容量原则

100 篇/天按通过验证的研究卡片计数，不按 Agent 调用次数计数。阅读 Agent 数量、单批任务量和并发度由模型吞吐、全文长度、API 限流和验证失败率动态决定，不写死为固定的“5 × 6”。

当前交付版仍有明确边界：只自动下载 OpenAlex 提供的开放获取 PDF；付费墙论文
需要用户自行合法取得并上传；图片扫描版 PDF 暂不做 OCR。系统不会把仅摘要分析
伪装成全文研读。
