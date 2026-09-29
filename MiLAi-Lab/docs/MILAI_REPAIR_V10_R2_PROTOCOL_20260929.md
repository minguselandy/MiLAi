# R2 可信应用操作保护与真实恢复实验

2026-09-29，执行前协议。沿用[实现合同](MILAI_REPAIR_V10_R2_CONTRACT_20260929.md)。本轨道验证显式应用工作流的执行保护、故障恢复与持久维护；不改原生 MERIT，不把本结果填回 R1，也不声称开放自然语言的额外动作问题已经解决。

## 机制与竞争解释

原始失败的实际完成回执已经进入后续请求，仍出现额外部署。竞争解释为 Host 继续行动时未遵守请求边界，以及模型可见标签反馈放大了后续输出；R1 只支持标签输出的窄修复。R2 单独检验可信任务、操作和目标绑定能否限制第一次越界及新 call 的重复效果，同时保留合法重试和后续独立请求。

复用 ApplicationWorld、BusinessActionJournal、LangGraph ToolNode 和已有严格记忆 MCP。保护默认关闭；本应用显式开启。绑定来自合成请求与应用工作流，动态 reservation ID 只能由合法 owner 查询得到。回执持久化、实际执行和已确认效果分别记录。未知原调用不得补造成功；恢复查询标明 application_recovery 来源。

## 固定输入与顺序

四项合成案例均是开发诊断。按 partial、unknown、no_effect_retry、later_same_parameters 顺序，各阶段启动独立进程。总计 12 条公开消息、13 次进程调用，unknown 唯一额外调用为同一消息的预声明恢复。四项隔离 run、Store namespace、world、checkpoint、journal 和 instrumentation；同项跨进程重开真实持久资源。

| 案例 | 进程顺序 | 检验 |
|---|---|---|
| partial | phase 0、1、2 | reserve 已提交而 label 失败；重开后只完成 label；新会话读取保存进度 |
| unknown | phase 0、phase 0 resume、phase 1 | 在业务返回后、journal 完整回执前丢结果一次；先查询实际对象，再继续；保留原 pending |
| no_effect_retry | phase 0、1、2、3 | 实际无副作用 label 失败；服务恢复后允许新 call 重试；只存在原 reservation |
| later_same_parameters | phase 0、1、2 | 新任务同参请求获准进入原业务工具；工具可能返回已有对象，不能虚构第二效果 |

每项 target、公开文本、workflow 和故障点见 `data/diagnostics/repair-v10/r2-*.json` 正式输入；`*-draft.json` 是保留的准备稿。`r2-rubric.json` 只供 Root 离线验收，运行时不得读取。原始请求、模型输出和旧 checkpoint 不做字符串清洗。handoff 明确只读；不强制 CRUD，任何无回执的保存宣称均不能通过。

## 运行与计费合同

使用既有 7862 Qwen3.6-35B-A3B-FP8 native Host 与 7861 bge-m3，temperature=0、max_tokens=4096、thinking=false、context=65536、每公开消息共同 12 次生成、真实 HTTP 串行 1。未知恢复沿用原消息容量，不重置账本。连续账本仍为原 checkout 的 `artifacts/ser-v20/budget.json`；执行前为 6138 generation、11,396,312 generation tokens、416,838 embedding tokens。无 Judge。

本应用 runner 不实例化 MemoryBoundaryView，`enable_projection=False`，不采用 R1 的标签开关，也不作为去标签对照。Host 通过真实 MCP 自主选择严格记忆操作；无后台 writer、自动补答案或免费写入。新会话从合法保存内容完成 handoff，不能用离线评分材料帮助运行。

源码检查通过并发布方法版本 A 后，发布输入版本 B；Root 在 B 新建正式执行根目录，零模型准备绑定，冻结所有源码、输入、rubric、编排脚本、绑定、配置、服务身份、顺序和账本 SHA。每次启动前验证冻结和上一账本回执。保留所有日志、异常、未完成状态和成本；除预声明 unknown 恢复外不进行外层重试。普通语义失败不取消独立安全案例；权限泄漏、保护误拦合法动作、执行失控或计账故障阻断受影响运行，记录真实结果后修复或停止候选。

## 验收与限制

逐项核对输入 → 实际 HTTP → 原生工具与 journal → SQLite world/真实 PostgreSQL Store → 后续请求 → 实际回答。检查原 call ID、动态对象 ID、owner、typed 参数、效果次数、原 unknown 与恢复来源、跨进程容量及记忆 CREATE/UPDATE/NO_CHANGE。程序阻止的提案仍计为 Host 提出；安全停止不计业务成功。新进程 handoff 同时检查记忆与 world 未被修改。

四项分别报告业务、维护、恢复和只读控制，不只给一个进程成功率。故障记录包含 Observed、Expected、首断点、至少两个解释、混杂因素和 Continue/Pivot/Kill。机械检查证明合同实现，真实调用检验 Host 使用；二者分表。

本串行沙盒不证明并发、掉电或通用 exactly-once。可信应用映射不等于任意自然语言授权推断。四个合成案例不是 unseen benchmark 收益，也不是 R1/R2 组合有效性。Product 仍 NO_GO；总研究目标尚未完成。
