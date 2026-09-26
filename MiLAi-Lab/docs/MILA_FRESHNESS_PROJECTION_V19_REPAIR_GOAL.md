---
date: 2026-09-26
status: A3_EXACT_REFRESH_PENDING
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
---

# v19 修复执行 Goal

完整执行用户新保存的 [747 行修复文档](v19修复.md)。新授权解除旧 v19 的 V5 gate，先用提交 `d0367aab36c15b39bdd4e2c1fd7a92a542f66fcf` 的现成 freshness_only 跑三个既有 fixture，不先改源码。旧 ODR 及旧结果封存，新工作不再以 reconstruction 为活动候选。

沿用一名 Sol xhigh 负责必要源码/config/tests/CI，Root 负责文档、冻结、环境、全部真实请求（并发 1）、费用和判定，Luna high 负责已授权的 Git 发布。原 vLLM、Host/embedding 设置不改；无 reviewer、思考模式、业务真值 gate、持续 State 或新基准数据。

## 顺序与验收

| 级别 | 内容 | 执行条件与证据 |
| --- | --- | --- |
| A0 B1 | 原基线参考 | 保留身份，不默认增加一轮真实对照 |
| A1 Notice | 现成 v19 freshness_only | 首先完整运行 changed/retained/irrelevant，无源码/schema/prompt 变化 |
| A2 Quarantine | request-copy 中逐项隔离 stale/deleted 正文 | 仅 A1 不足时开发、窄测和跑相同三例 |
| A3 Exact Refresh | quarantine + 同一对象的精确当前版本读取 | 仅 A2 不足时开发、窄测和跑相同三例 |

每级成功即停止升级，选择最简单的有效活动候选。三个实例必须真实初次取得 X@1，真实完成 frozen external update。Changed 需要取得当前 X@2 并在批准后仅记录一次 8°C；retained 必须实际取得 X@2，不能只用结果碰巧为 8°C；irrelevant 的 X 保持 current，Y stale 可被隔离，但不应重复搜索 X、额外搜索 Y 或改变温度。

A2 只改发送 Provider 的拷贝，不改 checkpoint、Store 或历史消息。搜索数组逐项处理，保持 current 项的原内容、顺序及 metadata；不能整条删掉 ToolMessage。结构化 freshness plan 包含 ref/status/current_ref/current_body_delivered/source_tool_call/item_index。CURRENT 原样，SUPERSEDED/DELETED 隔离，UNKNOWN 不伪装为 current；仅缺少新正文时说明未交付，不注入未读内容。增加简短、稳定、通用的 source-authority 原则，明确旧 assistant 结论不等于当前证据；不追踪其 proposition。

A3 仅在 stale material 实际将进入当前 request 时按同 namespace/memory_id 调用 public Store.get，不能 similarity search 或 embedding；提供经过精确 revision 核对的新 material，单列 exact reads、来源和真实 delivery。已交付当前正文时避免重复读，同 request 重复旧版本只需解析一次；deleted 不重新取回正文。无 semantic State、ack/completion，也无 reconstruction response field。额外读取 Y 必须单列，不能以没有模型 search 隐瞒 refresh 干预。

A1 为原合同；如 A2 同时引入隔离和 source-authority 原则，报告这是组合变化，不把结果归因成纯隔离效果。A3 与 A2 保持同一原则。无 current/stale 变化时保持同模式未干预行为，不改正常业务参数或禁止业务。

## 验证与留证

只做受影响的必要窄测：mixed search item/order/current 保留、stale/deleted/unknown/同文新版本、原 request 与 checkpoint 不被改写、next request 重算、A2 零自动读取、A3 exact identity/dedup/无 similarity、实际 material provenance 和普通工具/replay。新响应 schema 若与 B1 相同，不重复复制式 decoder probe；只在出现真实 transport 问题时补最小验证。更新包装声明才做一次必要 build；不做 full suite、12-case、MERIT 或 holdout。

旧 M1 mismatch 按 §16 单独作为 historical test expectation drift 处理，仅更新异常层级的期望或迁至历史回归；不得改变冻结 M1 运行语义。处理记录与 freshness 结果分开，不让它阻塞实验。

每级在真实请求前固定 source/config/fixtures/判定和空 namespace，失败不覆盖，不拼接轨迹。账本连续引用已封存 v19 的 20 次/20360 tokens/274 embedding tokens。A1 兼容旧 CLI 的 arms=3 元数据；若后续新入口采用四臂元数据，只记录元数据迁移，累计调用和 tokens 不清零，累计 caps 仍 null。

报告必须包含实际旧正文隔离、新正文取得、模型自然 search、精确 get、普通 ReAct 后续请求、实际业务动作、freshness/读取干预、tokens/embedding/存储、旧助手结论是否仍影响结果和所有失败。成功只支持这三个 exposed control，不升级为泛化或产品结论。全部必要实现/条件阶段判定、结果与复现、Luna 发布及远端核对完成后结项。

- [x] 原 v19 与新修复文档封存、A1 前冻结。
- [x] A1 三例：changed/retained失败，irrelevant通过，进入A2。
- [x] A2实现与必要验证完成；三例1/3通过，旧正文确实隔离，但changed/retained仍不重新取证，进入A3。
- [ ] 条件 A3 实现/必要验证/三例或有依据跳过。
- [x] historical test expectation drift仅更新异常期望，独立窄测1通过；M1语义不变，单独提交。
- [ ] 最终候选、费用、结果/复现、发布与远端核对。
