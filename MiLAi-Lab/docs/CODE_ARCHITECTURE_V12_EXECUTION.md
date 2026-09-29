# v12 执行与验收记录

状态：IN_PROGRESS；代码组织 Goal active，语义实验暂停。当前源码基线为 `cca2fd9`。
[计划](MILAI_CODE_ORGANIZATION_BOUNDARY_PLAN_20260929_v12.0.md)与[基线](CODE_ARCHITECTURE_V12_BASELINE.md)
定义完整范围；[验收矩阵](../data/manifests/code-architecture-v12-acceptance.json)按十五项完成判据逐项记录。

| 阶段 | 状态 | 完成要求 |
|---|---|---|
| S0 inventory / golden preparation | 盘点完成；分阶段继续冻结 | 全源import/owner/CI分组、实际断点分析、迁移前合同冻结 |
| S1 contracts / presentation | 实现中 | canonical Request/Memory/Operation合同、旧入口纯兼容、render等价 |
| S2 Memory core | 未开始 | MCP/strict tools/revision Store canonical、回执/Store合同等价 |
| S3 external integrations | 未开始 | Mem0/SimpleMem归属与SDK身份/语义保留 |
| S4 benchmark lifecycle | 未开始 | 提取公共prepare/start/finish/identity/costs，移除跨runner公共依赖 |
| S5 provider pipeline | 未开始 | 通用hooks与外部方法注入，冻结wire/容量等价 |
| S6 orchestration | 未开始 | writer policy独立归属，phase生命周期保留 |
| S7 boundaries / types / docs / publication | 未开始 | DAG/facade/identity/optional/build自动门禁、逐项验收与FastCI |

S0已完成170文件静态盘点、真实反向依赖定位及16个RequestContext渲染/4个错误基线。
Sol现负责S1源码迁移；S2–S5的专属golden仍须在对应改动前冻结，不能用S1检查替代。
旧代理在继续时已不在live列表，已按相同模型/职责重新启用Sol与Luna；Astra仅分析
S5旧构造参数兼容与无方法依赖之间的具体设计冲突，不承担源码写入。
原AGENTS按原字节归档，v12 plan按原字节复制，旧工作树/草稿/ledger保持。
源代码与检查只由Sol写入；Root维护本记录和验收；Luna负责分组提交和最终发布。

## S5 构造边界决定（实施前）

旧 `VLLMChatModel` 构造参数直接接收 M1/ODR/projection 控制器，以及 `memory_protocol="C"`
等标量。若要求旧参数自动激活原策略，就必须有一处识别研究方法；把这处藏进 Provider 的
包装器、动态导入或全局注册不能满足目标 DAG。

按计划第8节“当前 re-export 只保证当前兼容 import”和第15节“runner 注入具体 transforms”，
本轮允许迁移当前仓库内部构造调用者到方法/配方拥有的显式组装入口。旧 provider 模块仍是
canonical 通用类的纯 re-export。旧方法专属参数不得被通用类静默接受却失效；不承诺旧构造
参数自动组装策略。历史调用按原提交复现。

需要保持的是每个当前配方经过显式组装后的请求、wire、工具/Store行为、异常语义和容量顺序。
验收应比较冻结的旧行为与新组装路径，不能通过删除旧方法测试或改变期望输出来声称通过。
Astra只提供此具体设计问题的建议；实现仍由Sol统一负责。

具体S5接口、时序与兼容范围见[Provider设计决定](CODE_ARCHITECTURE_V12_PROVIDER_DECISION.md)。
