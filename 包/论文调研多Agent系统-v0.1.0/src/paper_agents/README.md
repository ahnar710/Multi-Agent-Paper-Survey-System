# paper_agents 核心包

核心包的分工如下：

- `agents/`：四个使用 DeepSeek 做语义判断的 Agent。
- `harness/`：LangGraph 顶层流程、论文队列、并发、重试和质量闸门。
- `providers/`：统一的大模型调用接口和 DeepSeek 兼容实现。
- `storage/`：SQLite 持久化。
- `tools/`：OpenAlex、Crossref、PDF 和去重等确定性工具。
- `ui/`：Gradio 网页。
- `schemas.py`：Agent 之间传递的数据契约。
- `state_machine.py`：任务状态允许怎样变化。
- `cli.py`：命令行入口。

