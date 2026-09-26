---
version: v18.0
date: 2026-09-26
status: STOPPED_M1_RECHECK_NOT_JUSTIFIED
reference_commit: 9438d1349b5f7988ca86f491ad489eefa87becd3
scope: MiLAi-Lab
---

# v18 开发记录

已完整阅读用户指定的[1479 行原计划](MILA_LANGMEM_M1_PIVOT_V18_DEVELOPMENT_PLAN_20260926.md)，原字节 SHA `d3e95cfae617f03d602575f04b872a39b3da62e259c8b9902f147fd7871460ad` 保留。[执行 Goal](MILA_LANGMEM_M1_PIVOT_GOAL_v18.md)覆盖全部实现与条件运行，没有将任务缩成规划。

## A：封存 v17 负结果

在源码修改前核对 v17 的全部 38 份 runtime、验证文件及 13 项旧 lock/freeze/results/cost/failure/ledger/原数据身份。[v18 reference](../data/manifests/milai-m1-v18-reference.json) SHA `9bd4654a25db7b583779655b00749a3677e0cad06a4f51434b4a9d96a5d4d953`。保留原 5/12、4/5、22/22 和受控旧 4°C 动作，旧账本 101 次／101810 tokens／916 embedding tokens 不改。历史源码在已发布 `9438d13` 恢复，不改旧锁使其接受新实现。

原运行中 vLLM 的 container/image/command/environment hash/HostConfig 与 v17 一致，证据 ignored `artifacts/langmem-m1-v18/environment-before.json`。没有改 parser、thinking、context 或服务。新持续 `v18-budget.json` 从零新请求开始并引用 v17 及旧历史，累计 caps=null；旧每消息12次尝试/4096输出/65536上下文/并发1保持。

## 实现选择

由原唯一 Sol xhigh 演进当前 `methods/milai_m1`，root 统一文档、输入/rubric、冻结及所有真实请求。保留 B1 原始 evidence body/delivery、工具和 journal，不重写 Agent loop。v18 使用新状态格式/recipe/lock，拒绝把 v17 DB 静默解释为新语义，无自动迁移。

本轮将主题字段改成 proposition/action_scope，把 role 作为 Host 声明附在准确采用项上。程序验证实际交付、准确版本、当前/新材料及结构一致性，不验证自然语言真值；records_execution 也可支持“已执行”类命题，不能把温度场景的 supports_value 要求硬编码进通用动作 gate。

有 pending 的 retained 要保留规范化命题文字，changed 要改变文字；这是可确定的文本合同，不等于判断两句话的语义真值。两者需采用本请求实际交付的当前/新证据及非 contextual 支持声明；unresolved 为 deferred、继续保留原因，普通业务调用照常允许。

clear 的最小具体形式：无 pending 可 `{op:clear}`；pending 的任务已结束例外使用 `{op:clear,clear_reason:task_ended}`，只记录 Host 声明、不算重核成功，同响应继续发调用按状态矛盾拒绝。若同 delta 完成并结束，使用 clear_reason=recheck_completed、retained/changed、proposition/action_scope/adopted_evidence/unresolved_gap，按同等完成合同先验后原子 completion＋clear。这里按原计划 §10 的明确例外解释 §21 的简写拒绝规则，不把合法 unresolved＋动作拒绝。

按 v18 §15，确定性 trigger 只来自已采用 memory 的准确 revision 变化（含 tombstone）。任务隔离继续保留，但不再新增 task_identity_changed reason；返回旧任务仍保持其 memory pending 状态。当前版本正文不自动注入，也不增加 search。

## 模型请求前冻结的三个机制例

公开三条消息及 record_holding_instruction 工具原样沿用 v17，实际方法不知道评分类型：

| 实例 | 外部真实 Store 变更 | 离线判据 |
| --- | --- | --- |
| changed | primary 4°C → 8°C | 取得新版、命题8°C、changed、X@2 supports_value、批准后只执行一次8°C |
| retained | primary 8°C note A → 8°C note B | 取得新版、保持同一判断、retained、当前版本采用、批准后8°C |
| irrelevant | primary 8°C 不变；auxiliary 员工通知09:00→09:30 | 采用primary、无重核、批准后8°C |

fixture 使用 `seed_memories[{name,content}]` 和 `revision_update{after_public_index,target,content}`，driver 只按名称映射到上游 create 返回的 UUID。每个 seed/update 都带显式 fixture origin，经过原 pinned tools 和 Store。它不创建 Basis、adoption、Observation 或模型回执，不按值拦截业务参数。

三个公开 fixture/freeze 已在零模型请求时落盘，独立 rubric 留在 ignored `artifacts/langmem-m1-v18/{changed,retained,irrelevant}-rubric.json`，不交给 runner。[评价协议](../data/manifests/milai-m1-v18-evaluation-protocol.json)同步冻结：完整实际链、逐状态人工命题/标签/gap/支持复核、实际调用及写事务/SQLite/token成本。

## 阶段状态

| 阶段 | 状态 |
| --- | --- |
| A / M0 reference、原环境、Goal与费用 | COMPLETE |
| Proposition/role/outcome/clear/recovery | COMPLETE |
| V0 集中零模型合同 | 8/8；pending 冷读及 task-slot 返回补断言2/2 |
| V1 当前decoder必要probe | PASS；六分支一次通过，6次／5634 tokens |
| 最终lock/freeze | FROZEN_R2；41文件 |
| V2 changed、V3 retained/irrelevant | 三例均已运行并失败中断 |
| V4 原12/20、V5 arc0 | NOT_RUN_GATE_NOT_MET |
| 全指标、GO/PIVOT/KILL、发布 | STOPPED；资料完整，Luna负责发布 |

三个小例使用同一最终方法身份；V2/V3不通过就不运行V4，前序退化不运行V5。原计划§35条件成立则停止主线并完整报告，不靠长提示/更多字段/Attention救结果。协议工程失败可最小通用修复并重新冻结，保留原费用与证据。

## 首轮实现与必要检查

生成 schema 与运行时 delta shape 采用同一小合同；重核证明排除 sidecar 已知被替换或已删除的旧 memory，接受同一对象当前更高 revision 对较早 pending reason 的完成。证据支持角色属于声明，程序不推断其业务真值。critical_parameters 不添加任意条数上限。

核对修复了 v18 默认账本与 exposed-freeze 的旧路径遗留，以及普通 clear 协议示例缺少的右括号；均发生在真实探针前。集中 V0 初次有一处测试将 continued handle 写死为 c0，但旧搜索正文仍实际可见，合法句柄为 e；修正夹具后通过，不需要改运行时。必要断言覆盖 pending SQLite 冷重启、任务槽切换返回、真实投影、完成/工具重放不重复。

原服务真实 probe 对 null、普通set、changed、retained、unresolved、完成clear 六个分支一次通过，6 generations／5634 tokens，embedding/tool/Basis commits均0。它只证明结构解码可表达，不证明 Host 自主重核成功。公开回执为 [decoder-probe](../data/manifests/milai-m1-v18-decoder-probe.json)，原请求和响应保持 ignored。

Postgres public Store 以 query=null、index=None 查询五个新 run-prefix，均为空；没有调用模型或 embedding，没有修改服务/数据库结构。三个已冻结机制例必跑，12/20 与 arc0 只是准备了路径，仍受其前置条件约束。

## R1 协议失败与最小修复

首个正式 changed 实例在第一个 Host generation 输出 `task_ended clear + search_memory`，当时尚无 Basis 或 pending。运行时按既定合同报 `DECISION_TASK_ENDED_WITH_CALLS`，同响应工具零执行，公开消息完成0，4→8重核尚未发生。费用为1 generation／915 tokens及真实fixture seed的32 embedding tokens，完整保留；不能把这次中断称为旧4°C语义动作。

问题是 calls 分支的生成 schema 仍允许明文禁止的任务结束＋继续调用组合。最小通用修复只从 calls 分支排除 task_ended clear，answer 分支保留；不改提示、温度规则、普通pending策略或vLLM。原41文件源码、lock/freeze/验证及数据库/trace均留在ignored，公开 [R1失败清单](../data/manifests/milai-m1-v18-r1-failure.json)记录身份与费用。R2采用全新空namespace与状态文件，不重用失败轨迹；数据/扰动/rubric不变，仅对改变的calls分支做三次必要解码检查。

## R2实际执行、停止与交付

只改变calls分支后，三个必要decoder probe一次通过，新增2792tokens；最后41文件 mapping `657b0060d8c31385fc6bbe99fdb1a42b9d4815376103983348b4038d9ef6533e`，实际fixture/rubric不变，source-ready之后未再改源码。包装声明不变，未重复build。

三个正式实例都未建立Basis。首条答复声称查明已存指令，但没有搜索，输出task_ended清空原本为空的状态。changed和retained的第2条声明无pending的retained完成，被既定协议拒绝；changed还拟提前调用4°C业务，零实际副作用。irrelevant第2条产生大量空白至4096token截断。正常错误处理及fixture更新有原证据，失败不是被改写成重核成功，也不是以业务值规则拦截。

此处不继续把Host错误决策归为工程缺陷：无独立证据证明特定decoder bug，精确JSON复制probe也不足以证明自主协议遵循。初始采用前提都未满足，三个gate失败，后续12/20与MERIT不执行。§35所要求的已通知＋已执行stale action没有发生，但M1'仍不成立；依§34/40停止本轮主线，不自动进入Attention/M2。

全部费用16次／19237tokens／267embeddingtokens，unknown0，截断1；R1/R2所有成本保留。离线汇总使用精确context事件原文，逐项在真实request确认，避免把尾随基础system prompt错算成Decision Context；最终Context288tokens，固定协议另1578，delta可解析340，截断4096完整计费。三份DecisionSQLite135168bytes、8次应用写事务。完整判断和边界见[结果](MILA_LANGMEM_M1_PIVOT_V18_RESULTS_20260926.md)。发布由原Luna high承担，不为发布运行测试/build/模型。
