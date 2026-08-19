# providers 文件夹

这里把模型调用封装成统一接口。Agent 只依赖 `ModelProvider`，不直接依赖某一家模型
SDK。`openai_compatible.py` 通过兼容接口连接 DeepSeek，便于以后替换模型供应商。

