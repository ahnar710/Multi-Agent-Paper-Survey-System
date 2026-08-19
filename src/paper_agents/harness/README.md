# harness 文件夹

这里是系统可靠运行的核心：

- `workflow.py`：LangGraph 顶层状态图和 checkpoint 恢复。
- `runtime.py`：逐论文 SQLite 队列、Worker 并发、租约与重试。
- `quality.py`：代码控制的质量闸门，防止模型自己给自己放行。

