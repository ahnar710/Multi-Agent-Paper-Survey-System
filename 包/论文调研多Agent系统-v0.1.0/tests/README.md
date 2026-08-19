# tests 文件夹

这里是自动回归测试，覆盖 Schema、四类 Agent 的关键规则、检索去重、SQLite、
HarnessRuntime 和 LangGraph 工作流。修改代码后在项目根目录运行
`PYTHONPATH=src python -m unittest discover -s tests -v`（Windows 可先安装项目再运行），
全部通过才说明基础行为没有被破坏；测试通过不等于学术结论一定正确，重要报告仍需人工抽查。
