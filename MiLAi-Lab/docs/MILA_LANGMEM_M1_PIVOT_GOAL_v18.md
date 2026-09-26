---
version: v18.0
date: 2026-09-26
status: STOPPED_M1_RECHECK_NOT_JUSTIFIED
implementation_authorized: true
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
reference_commit: 9438d1349b5f7988ca86f491ad489eefa87becd3
reference_source_mapping_sha256: 392c14287062a92465f74b31e402ea65099a55cb5136a1c3939b05dd1655b66f
development_plan_sha256: d3e95cfae617f03d602575f04b872a39b3da62e259c8b9902f147fd7871460ad
m1_lock_status: FROZEN_R2
v0_status: PASS
decoder_probe_status: PASS_R1_6_R2_3
changed_recheck_status: FAILED_INCOMPLETE
retained_control_status: FAILED_INCOMPLETE
irrelevant_control_status: FAILED_TRUNCATED
exposed_diagnostic_status: NOT_RUN_GATE_NOT_MET
exposed_merit_status: NOT_RUN_GATE_NOT_MET
cumulative_generation_request_cap: null
cumulative_generation_token_cap: null
cumulative_embedding_token_cap: null
---

# v18 执行 Goal：Proposition 与明确的重核完成

用户要求完整执行[1479 行原计划](MILA_LANGMEM_M1_PIVOT_V18_DEVELOPMENT_PLAN_20260926.md)。原计划保持字节不变；其 PLANNED_NOT_STARTED 是规划文件的历史状态，本 Goal 记录执行。目标是检验具体 action-sensitive proposition＋explicit outcome 能否让 Host 在普通 ReAct 中取得当前证据并完成正确重核，不把目标缩成 schema 兼容或代码存在。

## 1. 边界与组织

沿用 v17/B1 的实际交付绑定、准确版本、上游 LangMem CRUD/search、持久 Store、checkpoint、业务 journal、B1 sidecar。新实现继续放在 `methods/milai_m1`，通过小范围改动和参数化原 runner 接入，不复制 Agent loop，不复用旧 contextual 方法。

原 Qwen3.6-35B-A3B-FP8、bge-m3、服务容器/image/command/environment/HostConfig、parser、thinking、context 均保持。新协议由适配器实现，state 和 calls/answer 来自同一 generation。没有 State/reflection 专用调用、第二 reviewer、自动 search、ranking、candidate expansion、强制保存或 reconciliation、业务真值门禁、M2/Attention、新训练、Product/Archive 改动或新 seeds/holdout。

沿用一名 Sol xhigh 负责源码/config/tests/CI 和必要窄检查；root 负责 reference、Goal/报告、fixture/rubric/freeze、原环境、所有实际模型/embedding 请求（并发 1）、连续账本和独立评分；Luna high 按用户既有授权发布。无重复审批和常驻审核代理。

## 2. 必须交付的合同

- 单 task-local Basis：proposition、action_scope(subject,item,action_type,critical_parameters)、adopted_evidence(ref,support_role)、unresolved_gap、active/deferred、程序 recheck reasons、outcome。
- Proposition 应表达具体判断，其合理替代值会改变动作/参数/是否行动；主题标签不合格。程序不增加自然语言真值验证或 benchmark 专用规则。
- 每个 adopted ref 必须是当前实际交付或合法 continued exact ref。support_role 为 supports_value、constrains_applicability、records_execution、contextual，只代表 Host 声明；不改正文或推导 source provenance。
- 同 generation 的 null/set/clear 和严格 generation/runtime shape 对齐，避免重现 v17 宽松 schema／严格 reducer 不一致。
- 无 pending 时 outcome=null。有 pending 的 set 明确 retained/changed/unresolved；retained/changed 必须采用当前/新交付证据，不能仅旧版本；changed 的 proposition 必须确实变化；unresolved 为 deferred 且保留原因。
- Pending clear 必须符合原计划 §10 的任务终止或同 delta 完成重核语义，不能通过清空掩盖未处理的旧判断。程序只处理协议一致性，不判断业务参数真值。具体最小 wire shape 在开发记录中确定并冻结。
- Pending 本身不禁止动作；合法 unresolved＋业务调用允许执行并记录。非法 state/completion 在工具执行前明确报错，同响应所有工具零副作用；原工具参数错误维持原处理。
- Ack 记录 trigger/projected/completed 身份、outcome、new_adopted_refs。touch/clear/改标签不自动 ack。
- 不自动注入 current revision 正文、不自动 latest、不凭实体/embedding/scope overlap 制造语义 invalidation。原新 Observation 路径保留。
- 独立 Decision SQLite，明确格式身份；旧 v17 状态不得静默解释成 v18，无自动迁移要求。pending 重启保留、重复完成/请求/set 幂等、completed turn 不重复业务或记忆效果。

## 3. 冻结与实现门禁

| 包/里程碑 | 要求 | 直接证据 |
| --- | --- | --- |
| A / M0 | 冻结 v17 负结果与连续成本 | reference/source/locks/results/ledger/原服务 |
| B / M1 | Proposition/ActionScope shape | 非空命题、action_type/critical_parameters、旧格式拒绝 |
| C / M2 | SupportRole | 实际交付/continued、正文不变、unknown provenance |
| D–E / M3 | Outcome 与 ack | retained/changed/unresolved、pending clear、准确完成证据 |
| F–G | 执行边界与恢复 | 非法 completion 零副作用、普通 unresolved 可行动、独立状态/幂等 |
| V0 / M4 | 集中零模型检查 | changed/retained/unresolved、旧证据拒绝、clear、无关/tombstone、restart/replay |
| V1 / M5 | 当前 decoder 最少必要 probe | null、normal set、changed、retained、unresolved、clear |
| V2 / M6 | 新身份的原 4→8 机制 | X@1采用→触发→取得X@2→changed与supports_value→批准后8°C动作 |
| V3 / M7 | retained 与 irrelevant 控制 | 同值新版本取得后 retained；无关版本不触发 |
| V4 / M8 | 条件原 12/20 诊断 | 仅 V2/V3 通过后；语义/命题/非干预/采用角色 |
| V5 / M9 | 条件原 arc0 5/7 | 仅前序机制不退化后；金额支持、空搜索、生命周期 |
| M10 | 判断、全指标、复现、发布 | 全部失败和成本，GO/PIVOT/KILL 与限定结论 |

先完成实现、必要 V0/probe、最终 lock/freeze，再运行三个受控实例。数据、扰动时点与离线 rubric 必须在模型运行前冻结。fixture 只通过原 upstream tools 的显式外部 origin 扰动 Store，不预置 Basis/adoption、不把正确答案规则放进方法，不在模型看见的 prompt 里泄露评分条件。

V0 在正式运行前覆盖所有必要合同，包含 deferred、tombstone、重复 ack 后新 revision 再触发等；不运行全仓库测试。包装声明变化才 build。发布只做文件/身份核对，不再运行模型/测试/build。

## 4. 条件执行与停止规则

V2 成功需观察全部链：X@1 的 supports_value → @2 reason 实际送达 → Host 普通工具获得新版 → proposition 改为8°C → changed outcome → 采用 X@2 supports_value → 获批业务动作8°C。只触发、只改状态、只动作正确、自动补检索或第二调用都不算成功。

V3 两例与 V2 同最终方法源码：无关 Y 更新不能触发 X 判断重核；同值 X 更新要取得当前证据并 retained，防止把“版本变了”误作“判断一定变”。

V4 仅在 V2/V3 均通过后执行，V5 仅前序机制不退化时执行。条件不满足时按计划记 NOT_RUN_GATE_NOT_MET，不把条件运行省略说成全套 benchmark 已完成。原 12/20 与 arc0 的输入、世界、checker 和分母不改，不读新 seeds 3/4、fresh MemSyco 或 StateMemBench。

若新协议在通知已送达、普通工具可取得证据、无额外调用/真值门禁条件下仍执行 stale 4°C，严格执行原计划 §35：停止当前 Decision Basis＋Selective Recheck 主线，不增加字段/提示长度/Attention/reviewer/逐温度规则来救结果。协议工程错误可做最小通用修复、保留失败并重新冻结；不得把语义失败伪装成工程异常无限重跑。

## 5. 独立指标与费用

在首个真实请求前冻结人工 rubric：具体命题质量、label-like、action-critical grounding 的 Host 声明覆盖、实际支持质量、changed/retained/unresolved 完成、正确动作、非干预。指标给分子/分母及观察范围；实际 evidence 有效性不等于语义充分性。

单列 Decision Context 输入 tokens、decision_delta 输出 tokens、recheck completion 字段 tokens、独立额外 generations、Decision SQLite bytes 和写事务数。基础请求总费用同时报告，不能只报状态片段而漏掉协议固定文本。与 v17 同口径比较，条件未运行的组不虚构数字。

v18 独立持续账本引用封存 v17 的 101 次／101810 tokens／916 embedding tokens及更早历史。失败、unknown、probe、必要修复全部计入，不清零。累计 caps=null；原每公开消息 12 次尝试、4096 输出、65536 上下文、并发 1 保持。开发代理费用与实验 Provider 用量分开，无额外 Judge。

## 6. 交付与终态

交付新 v18 config、薄 CLI/inspection 入口、三个 fixture、reference/lock/final freeze、集中测试、完整开发/结果/复现文档、机制与条件运行 manifests、连续成本汇总及发布回执。原用户计划文件也纳入提交但不改字节。

仅在全部必要实现/机械验证/三个小例/条件判断和资料完成后结项。按实际证据选择 COMPLETE_WITH_M1_RECHECK_COMPLETION、COMPLETE_WITH_RECHECK_EXECUTION_FAILURE 或 STOPPED_M1_RECHECK_NOT_JUSTIFIED；不把缺失工作重新定义成负结果。GO 才可讨论 M2，本轮不实现 M2。

- [x] 原计划全读，核对 v17 38 文件及封存失败/结果/账本，原服务不变。
- [x] Proposition、SupportRole、Outcome、clear 一致性、持久化和恢复。
- [x] V0 全部必要合同、当前 decoder probe、最终 R2 lock/freeze。
- [x] changed/retained/irrelevant 三个机制实例均实际尝试并独立判定失败；不把中断记为全轨迹完成。
- [x] V4/V5 因前置失败明确关闭，保留全部失败和费用。
- [x] 指标、停止判断、开发/结果/复现与发布资料完成；Luna 按既有授权发布，远端核对由最终交付回执记录。

## 7. 实际结项依据

[结果](MILA_LANGMEM_M1_PIVOT_V18_RESULTS_20260926.md)与[复现](MILA_LANGMEM_M1_PIVOT_V18_REPRODUCTION_20260926.md)完整记录本轮。最终41文件 mapping `657b0060d8c31385fc6bbe99fdb1a42b9d4815376103983348b4038d9ef6533e`；三个R2实例都在第2消息中断：changed/retained为无pending的完成声明，irrelevant为4096token空白输出截断。各完成1/3公开消息，没有搜索、接受Basis/adoption、触发或业务执行。质量/label/grounding有效率为0/0不可估计，不能声称命题改善。

R1的task_ended＋calls schema组合遗漏已做最小通用修复，保留原失败和费用；R2不继续添加schema状态分区、提示或自动检索以救负结果。原计划§35精确条件未满足（没有revision通知或已执行旧值），因此不声称复现该特定kill事件；按§34/40核心机制仍未成立，终态STOPPED_M1_RECHECK_NOT_JUSTIFIED，M2未准入。

所有v18成本16 generations／19237tokens／267embeddingtokens，unknown0、Judge0、截断1，旧费用不动。必要8项V0及修复相关检查、原服务9次probe、一次R1包包含检查通过。没有大规模测试、完整套件、额外State/reviewer、vLLM设置变更、Product变更或新holdout。仅受条件约束的V4/V5未运行，执行计划的实现、小实例尝试、条件判定、证据与报告均已交付。
