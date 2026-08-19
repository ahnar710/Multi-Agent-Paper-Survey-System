# GNSS 多径前沿研究：检索计划 v0.1

## 术语边界

- `multipath`：接收机同时收到直达信号与一个或多个反射信号。
- `NLOS`：直达信号被遮挡，接收机主要收到反射或绕射信号。
- 两者可以共存，但筛选与研究卡片必须分别标注，不能把所有城市环境误差统称为多径。

## 核心英文检索式

以下词组将与 `GNSS OR GPS OR BeiDou OR Galileo` 组合：

1. `multipath mitigation OR multipath estimation OR multipath detection`
2. `carrier phase multipath OR sidereal filtering OR multipath hemispherical map`
3. `NLOS classification OR LOS NLOS detection OR measurement weighting`
4. `deep learning OR machine learning OR random forest OR transformer`
5. `direct position estimation OR factor graph OR robust estimation`
6. `antenna array OR beamforming OR polarization OR choke ring`
7. `3D mapping aided OR shadow matching OR LiDAR aided OR vision aided`
8. `urban canyon OR autonomous driving OR low-cost receiver OR smartphone`

## 首轮来源顺序

1. Crossref/OpenAlex/Semantic Scholar：广覆盖元数据与引用关系
2. IEEE Xplore、ION、GPS Solutions、Navigation、Satellite Navigation：专业论文
3. arXiv：追踪最新预印本、代码和开放数据
4. 厂商与标准资料：只用于产品约束，不替代学术证据

## 初始配额

每天输出 100 篇通过验证的全文研究卡片。各路线配额见主题配置文件；若某路线合格全文不足，由编排 Agent 按候选池质量动态调剂，并记录调剂原因。

## 单篇产品化判断

除学术结论外，每篇论文必须回答：

- 方法作用于射频、基带、观测量还是定位解算层？
- 需要消费级还是测量级硬件？是否依赖相关器输出或原始 IQ？
- 是否可实时运行？论文是否报告延迟、算力或模型大小？
- 是否跨城市、接收机、天线、频点和星座验证？
- 与现有接收机软件栈的集成成本和主要风险是什么？

## 首轮校准文献

- 2024 年载波相位多径综述：用于建立 SF、MHM、随机模型与函数模型分类。
- 2024 年随机森林多径参数估计：用于校准学习方法与 MEDLL 等经典方法的比较字段。
- 2024 年低成本天线研究：用于校准硬件、频点和天线相位中心相关字段。
- 2025 年学习增强滤波与直接定位预印本：用于追踪 AI、困难样本挖掘和端到端位置改正路线。

