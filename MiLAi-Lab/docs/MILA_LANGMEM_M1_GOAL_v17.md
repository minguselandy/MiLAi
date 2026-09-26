---
version: v17.0
date: 2026-09-26
status: COMPLETE_WITH_M1_LIMITATIONS
implementation_authorized: true
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
method_scope: M1_SPARSE_EVIDENCE_GROUNDED_DECISION_STATE
reference_commit: 3676c511f4c4087453d5bbf54cea3514e57fd948
reference_source_mapping_sha256: ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea
development_plan_sha256: 88eab77766ab8ff22730d653f7140a3476aedfe208f816b3c388604054ba1883
m1_lock_status: FROZEN_R2
v0_status: PASS_WITH_POST_RUN_MECHANICAL_SUPPLEMENT
controlled_mechanism_status: TERMINAL_RECHECK_NOT_COMPLETED
exposed_diagnostic_status: COMPLETE_12_CASES_20_SESSIONS_5_SEMANTIC_PASS
exposed_merit_status: COMPLETE_5_EPISODES_7_MESSAGES_NATIVE_4_OF_5
cumulative_generation_request_cap: null
cumulative_generation_token_cap: null
cumulative_embedding_token_cap: null
verification_count_cap: null
---

# v17 执行 Goal：Sparse Evidence-Grounded Decision State

用户已明确要求完整阅读并执行[1553 行 v17 计划](MILA_LANGMEM_M1_V17_DEVELOPMENT_PLAN_20260926.md)。本 Goal 将该计划落到实现、冻结、有限运行和方法判断；不替换或缩小原目标。原计划字节保留，其 PLANNED_NOT_STARTED 是交付计划时的历史状态。

本轮仅增加 `M1 = B1 + Sparse Decision Basis + Explicit Adopted Evidence + Program-Owned Recheck`。不是再做一个更强的基线，不以原 7/12 或 4/5 提分作为完成标准。需要交付完整可恢复机制，并用真实 LLM 的受控诊断及原 exposed 数据判断它是否自然稀疏、选择性采用、能重核且不增加独立模型调用。

## 1. 固定范围与组织

保留原 LangMem 0.0.30、upstream `9d033b47d9ce53e37e92c92241b0496c0278932e`、业务工具、Store、checkpoint、B1 instrumentation 和 action journal。Qwen3.6-35B-A3B-FP8、bge-m3、现有服务容器及 vLLM parser/thinking/context/服务设置不改；新输出协议由 adapter 表达。

新机制放在 `methods/milai_m1`，只在原 Agent/Provider/runner 增加必要的 opt-in 接口。默认 B0/B1 行为不变，不复制整套 Agent loop 或 benchmark runner。共享文件改变使用新 `milai-m1-v17.lock.json`；旧 B1/foundation lock、v16 结果与账本不改，旧版本在固定 commit／参考快照复现。

禁止自动 query/ranking/candidate/stop 控制，禁止自动 search/save/update/delete/reconciliation、强制未来承诺保存、无证据就阻止 action、gap 非空就强制 search、第二审核模型/reflection/Jev、support graph、训练、Product/Archive 或旧 contextual 方法改动。M2/Attention、新 MERIT seeds 3/4、fresh MemSyco、StateMemBench、正式 matched evaluation 均不运行。

沿用一个 Sol xhigh 负责全部核心实现和窄测试；root 负责文档、reference/lock/freeze、诊断输入和独立评分、环境、全部真实请求（并发 1）与连续成本。Luna high 按既有授权承担必要下载和最终 GitHub 发布，无常驻 reviewer。用户执行和发布授权已足够，不添加重复审批流程。

## 2. 必须实现的状态合同

每个 `(run_id, arm_id, user_id, task_id)` 只有一个 active slot。独立小 SQLite 只保存当前 Basis、历史 delta/ack 和恢复身份，不复制完整 memory body、LangMem Store、checkpoint 或 B1 sidecar。

Basis 包含 `decision_id/revision/task_id`、有行动意义的 `decision`、`scope(subject,item,context)`、`adopted_evidence`、`critical_gap`、`host_status` 和程序持有的 `recheck_reasons`。Host 状态只有 active/deferred，不能直接写 needs_recheck。最多采用 8 项准确证据；Host 只写短 handle，程序绑定 kind/exact ref/content hash/delivery identity。

与正常 calls/answer 在同一次 JSON-action generation 输出 `decision_delta = null | set | clear`，不新增状态专用生成、不设计复杂 patch。

- null 保持当前 Basis，不确认 recheck。
- set 完整替换语义字段，准确证据由程序解析；相同规范化语义状态为 NO_STATE_CHANGE，不增加语义 revision。
- clear 结束当前 task Basis，保留历史事件。
- `critical_gap=null` 不自动 clear；仍影响后续行动的 grounded decision 可以继续存在。
- gap 仅表示其不同答案会改变下一 meaningful action、参数或是否行动的缺口。
- 普通闲聊、格式任务、task summary、纯记忆转述或已无后续影响的完成判断，不要求建立状态。

输入验证中的非法 delta 必须有明确拒绝证据且不执行同响应工具。工具参数仍由原 schema 验证；不把状态错误伪装成已经执行过的业务结果，不添加运行时语义审批或自动修复层。

## 3. Evidence View 与实际交付

来源仅为当前请求中的真实用户 Observation、业务 Observation/receipt、memory search delivery，以及当前 Basis 合法继续采用的 exact refs。区分 available、delivered、adopted；出现在 Store、sidecar 或搜索返回却未进入请求，不构成首次 adoption 资格。

首次采用必须能连到该 generation 的实际 Provider request，准确正文、Observation identity 或 memory revision 可恢复。相同文字的不同 Observation 不合并。继续采用旧 ref 可以不重复正文，但必须标记 continuation，不声称重读，也不自动跟到 latest。

Evidence handles 只增加短 ref、kind、exact identity，不重复大段材料。一个紧凑 Decision Context 展示当前判断、scope、已采用 refs、gap、投影状态、recheck 和新 Observation refs，不注入完整 sidecar/revision history。原 user/ToolMessage/business content 仍走原路径。

`memory provenance=UNKNOWN_NOT_DECLARED` 与 `decision adoption` 严格分开。采用 X@2 不证明它由用户支持；成功 receipt 只证明结果，不证明动作参数语义正确。gold/rubric 不进入方法或证据。

## 4. Program-owned recheck 与恢复

首版 trigger 仅为已采用准确版本被 supersede、被删除/tombstone、task identity 改变。无关版本不触发。程序保持 adopted=X@1，投影 current=X@2 的原因，不自动改写 decision/ref 或判断语义为假。

所有未结束 Basis（包括 deferred 状态）在下一次正常请求看到新 Observation refs；没有 dependency edge 不能漏掉新输入，也不能凭 subject/hash 认定判断失效。Host 仍自由选择 keep/change/search/read/act/no-op/clear。

重核确认要求该实际请求包含与原因相关的新材料，并提交合法 delta；仅新版本存在、仅 null、仅旧正文重交付都不确认。changed revision 的新正文需通过正常交付获得；删除与 task 切换按可核对的新通知事实处理。ack 与语义 state change 分开，Host 不能覆盖程序原因，相同已确认变化不能每轮重复触发，新变化仍可触发。

进程重启必须恢复同一 task 的 Basis、pending recheck 和已完成事件。重放 completed turn 不新增 decision revision、业务动作或 memory 操作；不通过新 run ID 掩盖 pending 业务，也不扩大 v16 的跨库原子性声明。任务变化不能携带上一任务 active slot。

## 5. 工作包与门禁

| 工作包 | 原计划章节 | 交付与直接证据 |
| --- | --- | --- |
| A / M0 reference | §20、§39 | v16 commit/27 文件 mapping、lock、上游、recipe、服务、数据、journal 和成本封存；新 Goal |
| B State Store | §5–10、§21 | 单 task slot、持久 delta/ack、null/set/clear、相同 set no-op、gap-null、deferred、restore |
| C Evidence View | §11–12、§22 | actual request 交付见证、首次/续用边界、准确 Observation/版本、undelivered 拒绝 |
| D Transport | §9、§23 | 同 generation delta+calls/answer，调用顺序、原参数检查、非法 delta 零工具执行，部署 decoder 可表达 |
| E reducer | §24 | 准确绑定、稀疏可选状态，Host 不覆盖程序 reason，无重复语义 revision |
| F recheck | §13–18、§25 | update/tombstone/task trigger、无关变更无触发、不 latest、合法新材料后 ack |
| G recovery | §26 | 冷恢复 Basis/recheck、completed turn 幂等、原 journal 合同保持 |
| V0 | §27 | 少量集中零模型机械检查、受影响静态/边界、默认关闭合同 |
| V1 / M6 | §28 | 运行前冻结的 M1_MECHANISM_DIAGNOSTIC，真实普通生成中的 adoption→revision→recheck→重新判断 |
| V2 / M7 | §29 | 原 12 例／20 会话完整 exposed 诊断，激活/选择性/gap/churn/任务行为 |
| V3 / M8 | §30 | 原 arc0 全 5 集／7 消息，金额判断、空搜索gap、receipt与自然update/recheck |
| M9 结果 | §32–42 | 全部失败、追踪/状态成本、指标与 GO/PIVOT/KILL，不声称未见效果 |

顺序为 reference → B–G 实现／必要 adapter decoder probe → V0 → final freeze → V1 → V2 → V3 → 独立分析。M3 probe 只验证当前部署的输出协议，所有费用进入同一 v17 账本；V0 本身零生成。

V0 覆盖 delivered Observation/memory、undelivered、stale/latest 混淆、同文不同事件；全部状态转移；X@1→X@2／tombstone、无关变化、ack 条件；两种 envelope、非法 delta 零副作用、原工具错误、无独立二次生成。只运行相关窄测试；新增包需边界检查，实际 sdist/依赖声明改变才做一次必要 build，发布不重跑。

V1 输入与任何受控变更在请求前冻结，不读取 MERIT gold，不计 benchmark 分数。受控 Store 扰动必须明确标注为 fixture 操作，不能把预制状态、伪造 adoption 或方法内强制更新说成自然到达。方法不因案例 ID 或目标答案改变。若自然链未到达，保留失败并定位通用机制；必要修复重新冻结，不拼接不同实现的成功片段。

V2/V3 数据、原生 checker 和分母不变，最终源码从原世界和空 M1/B1 namespace 完整执行。Basis 几乎不激活或过度激活也必须完整报告，不为达到好结果强制每轮 set、强制保存或不断增加 prompts/模型调用。

## 6. 独立指标与费用

必须给出分子、分母及时间口径：

- activation：有未结束 Basis 的 model turns / all model turns；active/deferred/needs_recheck 分列，不能越高越好。
- churn：semantic basis revisions / active basis turns；identical set/no-op、clear、ack 独立计数。
- adoption validity：实际 delivered 或合法 continued exact refs / accepted adoptions；目标 100%，不能把格式合法当作正文已交付。
- selectivity：每请求 delivered 数、adopted 数及其关系；审查是否全材料照收。
- gap quality、task-summary state、non-intervention：按冻结含义规则人工判断，报告样本和理由。
- recheck：trigger/projection/ack、decision retained/changed、追加正常 read/search；版本变化本身不是成功。
- 任务行为：原 12 例语义与完整 native/dependent 分母、业务实际执行／回执；对 exposed 分数变化只称 development signal。

单列 Decision Context input tokens、decision_delta output tokens、activation、semantic revisions、recheck projections、extra independent generations。核心要求是没有独立 State/recheck/reflection 模型请求；正常 ReAct 次数差异与错误恢复请求如实计费，不能靠将它们改名隐藏开销。

v17 使用独立连续账本并引用 v16 封存 55 次／40072 tokens／443 embedding tokens及更早历史。累计 caps 为 null，每公开消息 12 次尝试、4096 输出、65536 上下文、真实并发 1 保持。失败、unknown 预留、probe、必要复核全部保留；开发代理费用另列，不冒充实验模型费用。默认原生 checker＋有限人工复核，无额外 Judge 必要时不增加。

## 7. 终态与 M2 判断

技术实现、恢复、输入合同及完整声明运行均需真实证据后才能结项。允许三种诚实结果：

- `COMPLETE_WITH_M1_MECHANISM_REACHABLE`：实际链成立，稀疏/选择性/成本和普通任务边界可评估。
- `COMPLETE_WITH_M1_LIMITATIONS`：完整交付但存在已证实机制限制，不能把缺失工作称为限制结项。
- `STOPPED_M1_NOT_JUSTIFIED`：计划中的反证条件成立，说明方法不能形成及已执行范围。

GO→M2 必须同时满足非零真实 adopted evidence、不全材料照收、至少一个真实自然/受控 recheck 链、activation 不退化、状态成本可接受、未明显损害普通任务、无独立额外模型调用。否则按计划 §34 的实际证据作 PIVOT/KILL；不因有代码、green tests 或分数变好自动 GO。本轮不执行 M2。

完成交付：

- [x] 原计划全读，v16 reference 与新执行 Goal。
- [x] 单槽 State Store/reducer、Evidence View、程序 recheck、同 generation adapter 和恢复。
- [x] 当前 decoder 的必要 probe、V0 窄检查、默认分支保持与最终 lock/freeze。
- [x] 预冻结机制诊断、原 12 例与完整 arc0 的最终源码运行及全部失败费用。
- [x] `MILA_LANGMEM_M1_V17_DEVELOPMENT_20260926.md`、`MILA_LANGMEM_M1_V17_RESULTS_20260926.md`、`MILA_LANGMEM_M1_V17_REPRODUCTION_20260926.md`。
- [x] m1 lock、final freeze、mechanism diagnostic manifest、cost summary、exposed-run manifests和 GO/PIVOT/KILL。
- [x] Luna high 按既有授权发布全部开发，核对远端 SHA 和工作区。

## 8. 最终验收

[最终结果](MILA_LANGMEM_M1_V17_RESULTS_20260926.md)：R2 mapping `392c14287062a92465f74b31e402ea65099a55cb5136a1c3939b05dd1655b66f` 下完整交付 A–G、V0、预冻结受控机制、原 12/20 和 arc0 5/7。R1 schema 宽松造成的三个非法 clear 中断已通过仅 adapter schema 修复解决，R1 全部源码与费用保留。最终 53 次普通生成无拒绝，采用准确性 22/22、activation 21/53、语义 set revisions 14、独立 State/reflection 0 次。

真实重核只有 trigger 1／projection 2，ack 0，受控业务仍执行旧 4°C；原诊断语义 5/12，arc0 native 4/5、dependent 1/2。全部 14 个语义状态中 9 个主要是主题标签，非干预仅 3/4。故结论为 `PIVOT_REDESIGN_M1_BEFORE_M2`，M2 不进入；完整开发/验证结束不等于方法有效。

累计 v17 101 次生成／101810 tokens／916 embedding tokens，unknown=0、Judge=0，含全部 R1 失败和两轮必要 decoder probe。vLLM、旧锁/费用和原计划字节均核对不变。发布沿用 Luna high 授权，远端 commit/工作区核对记录在最终交付回执；不为发布重跑模型或测试。
