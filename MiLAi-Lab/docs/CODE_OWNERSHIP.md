# Lab 代码职责

本页定义 v12 的维护归属；迁移进度和实际验证以[执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)为准。
目录存在不表示研究方法已启用，也不表示语义效果通过验收。

| 归属 | 负责的行为 |
|---|---|
| `contracts` | 请求、记忆、操作等轻量数据合同；不执行业务或模型调用 |
| `application` | 业务世界、操作 journal、真实工具和恢复观察 |
| `memory` | 通用 Store/MCP、严格记忆操作、版本及材料呈现 |
| `providers` | 模型协议、HTTP、容量和实际 usage；接受显式注入的通用 hooks |
| `integrations/memory` | 外部记忆 SDK 的配置、生命周期和公开接口适配 |
| `methods` | 研究策略、方法状态和向通用接口注入的具体实现 |
| `benchmarks` / `harness` | 共同执行设施及结果制品；原生任务与 scorer 保持独立 |
| `runners` | 方法组装、运行阶段、资源打开/关闭与交接 |
| `analysis` | 已发生 trace、费用和证据的离线分析；不改变运行时动作 |
| `datasets` | 来源固定与合法输入；不把评分答案交给运行时 |
| `scorers` | 原生/声明的评分合同，与实际运行输入分离 |
| `tools` | CLI 参数与薄入口 |

`baselines` 保留实际 baseline/Agent 配方；已迁移实现的旧路径只提供同一对象的 re-export。
不因文件属于旧目录就全部迁走；以调用者和状态归属判断是否需要提取。

Root 负责协议、合成验收输入、文档和集成验收；一个 Sol xhigh 负责源码、配置、测试和 CI；
Luna high 负责 Git 发布。每个文件同时只有一个写入负责人。Astra 只参与已明确的困难问题。

变更需要同时核对 canonical 源码身份、验证矩阵、可选依赖分组及兼容入口。
旧报告、实验锁和失败轨迹按原提交复现，不能用新组织结构改写旧结论。

`baselines/` 不是一个统一的底层服务层：真实 Agent/方法配方、观察设施、身份模块和完整 facade
必须按实际职责区分。它们均不能反向导入 runner；旧目录名不能成为隐藏依赖的豁免。
S7 已将活动源码的 owner 与实际验证组对应，证据见阶段报告；仅属于 Foundation discovery
范围不能替代真实 strict 检查和所需可选依赖。
