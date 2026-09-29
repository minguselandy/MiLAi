# v12 代码结构整理总体报告

状态：本地工程整理与验收完成。S0–S6 已保留分阶段提交；S7 待集成提交与远端 Fast CI、合并。
基线为 `cca2fd9d1cb4614c44a40ddc0458325d959e6740`，完整范围见
[v12 计划](MILAI_CODE_ORGANIZATION_BOUNDARY_PLAN_20260929_v12.0.md)与
[十五项验收矩阵](../data/manifests/code-architecture-v12-acceptance.json)。
本页报告工程整理，不是新增实验效果报告。实验仍暂停，Product NO_GO。

## 已收敛的维护位置

| 能力 | 当前实现归属 |
|---|---|
| 请求、scope、记忆/操作及 benchmark 数据合同 | `contracts/` |
| 严格记忆 CRUD、MCP、版本 Store、通用材料呈现 | `memory/` |
| 业务 world、journal、工具与恢复 | `application/` |
| Mem0/SimpleMem 原生 SDK 适配 | `integrations/memory/` |
| 通用模型请求、实际 HTTP、容量、decode 与 hook 合同 | `providers/chat_bridge.py`、`request_pipeline.py` |
| C/M1/ODR/projection 等具体方法注入 | `methods/langmem_recipe.py` |
| 共同 benchmark prepare/start/finish 与费用聚合 | `harness/benchmark_execution.py` |
| writer 策略与实验运行顺序 | `runners/writer_policy.py`、应用 phase/runtime runners |
| 原 LSA trace 计账 | `analysis/trace_accounting.py` |

拆分以实际调用和职责为依据，保留必要的实验组装。没有按文件大小重写历史方法，也没有
新增业务事实库、Reviewer、语义 selector 或对象平台。完整维护入口见
[项目地图](PROJECT_MAP.md)、[架构](LAB_ARCHITECTURE.md)、[依赖规则](DEPENDENCY_RULES.md)。

## 分阶段证据与提交

| 阶段 | 提交 | 证据 |
|---|---|---|
| S0 盘点与冻结准备 | `19339bff` | [基线](CODE_ARCHITECTURE_V12_BASELINE.md) |
| S1 contracts / presentation | `02dfacdc` | [S1](CODE_ARCHITECTURE_V12_S1_RESULTS.md) |
| S2 Memory core | `379ad45e` | [S2](CODE_ARCHITECTURE_V12_S2_RESULTS.md) |
| S3 外部集成 | `5aa61b8d` | [S3](CODE_ARCHITECTURE_V12_S3_RESULTS.md) |
| S4 benchmark 公共流程 | `2bc50583` | [S4](CODE_ARCHITECTURE_V12_S4_RESULTS.md) |
| S5 Provider / 方法解耦 | `96a6ce17` | [S5](CODE_ARCHITECTURE_V12_S5_RESULTS.md) |
| S6 writer 编排与 trace 计账 | `c8b7d81a` | [S6](CODE_ARCHITECTURE_V12_S6_RESULTS.md) |
| S7 自动边界、类型与发布 | 本地完成；发布待验 | [S7](CODE_ARCHITECTURE_V12_S7_RESULTS.md) |

迁移前冻结合成输入和合法错误，迁移后比较原消息、实际 MockHTTP、工具/Store、回执、
持久化、容量与费用；必要构建核对 sdist/wheel 和安装来源。各阶段报告列出检查范围、
失败尝试及修正，不把重复检查次数相加为独立测试覆盖。

S3 的计时、S6 的集合顺序及 SDK 内部随机字段使用固定测试条件补充对照，原差异不删除。
S5 保留零工具 JSON 路径原有的 HTTP 后 schema 错误，没有把机械等价升级为任务成功。
S6 最终 EOF 格式修正只补包字节核对，安装回放证据明确属于此前行为相同的 wheel。

## 兼容范围与限制

完整搬移的旧路径只导出 canonical 对象；仍承担实际 phase 的 runner 不是整文件 facade。
当前请求、工具/Store、JSON/SQLite、权限、模型参数和费用规则保持。

通用 `VLLMChatModel` 不再接受方法专属参数并自动组装策略；当前调用者已迁到显式方法 recipe。
通用构造器拒绝这些参数，不静默忽略。历史调用按原提交复现，不能把这次结构整理描述为
所有旧构造参数均向后兼容。详见[设计决定](CODE_ARCHITECTURE_V12_PROVIDER_DECISION.md)。

旧锁、原研究分母与失败继续保留。R2 的错误正文真实持久化未被修复；标签改善不证明行动
可靠性，第二模型家族和稳定 unseen 收益未完成。研究结论仍以
[v10 总体实验报告](MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md)为准。

## 最终门禁与发布

S7 正式 DAG/facade/identity/type/optional/package 门禁已完成，详细检查见 [S7 报告](CODE_ARCHITECTURE_V12_S7_RESULTS.md)。
[当前清单](../data/manifests/code-architecture-v12-current-import-map.json)记录 194 个源文件的实际归属与类型分组；
[保留核查](../data/diagnostics/code-architecture-v12/final-preservation-evidence.json)确认 190 份基线证据字节未变、Product/Archive 实现未改、旧草稿仍在。

本轮新增真实 Host/embedding/Judge 调用均为 0。连续账本保持 6,145 次 generation、
11,407,086 generation tokens、416,930 embedding tokens；没有清零费用或修复历史失败。

十五项判据中十四项本地通过，C13 等待本次实际发布实现对应的 Fast CI。
尚无本轮 GitHub PR 或合并 SHA，不能以既有 main 的 CI 代替。
结构回滚基线为 `cca2fd9d1cb4614c44a40ddc0458325d959e6740`，分阶段提交便于逐项审查。
