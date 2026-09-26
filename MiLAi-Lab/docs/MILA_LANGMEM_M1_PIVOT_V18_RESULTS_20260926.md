---
version: v18.0
date: 2026-09-26
status: STOPPED_M1_RECHECK_NOT_JUSTIFIED
experiment_arm_kind: RESEARCH_PROTOTYPE
source_mapping_sha256: 657b0060d8c31385fc6bbe99fdb1a42b9d4815376103983348b4038d9ef6533e
---

# v18 结果：协议工程完成，自主机制未成立

Proposition、ActionScope、SupportRole、明确 outcome、重核完成校验、持久化与重放已实现，通过必要零模型检查及当前解码器 probe。最终 R2 的三个小实例均未完成目标链：Host 没有搜索或建立 Basis，两个实例输出无 pending 的虚假完成，另一个输出空白直至截断。**本轮停止当前 M1 主线，终态 `STOPPED_M1_RECHECK_NOT_JUSTIFIED`，不进入 M2。**

这不是三例完整业务执行后得到的准确率，而是三个预先冻结实例的失败运行。原12例／20会话与MERIT arc0均按前置条件记 `NOT_RUN_GATE_NOT_MET`，未消费新seed/holdout。没有用协议拒绝后的零业务效果宣称动作安全性或重核有效。

## 方法与环境身份

- 原 v17 commit `9438d1349b5f7988ca86f491ad489eefa87becd3`，其源码/结果/锁/费用保留。
- 最终41文件 mapping：`657b0060d8c31385fc6bbe99fdb1a42b9d4815376103983348b4038d9ef6533e`。
- 新 [v18 lock](../data/locks/milai-m1-v18.lock.json) SHA：`200e8119ee09b1b8cbb5085e51f21c2b11c76755f5c5b335f3a09f1c48d54c11`。
- [最终冻结](../data/manifests/milai-m1-v18-final-freeze.json) SHA：`20407ea9ec505e7361dee8fdc8b5e33577bed9fb1d095982747254cf708dd9c2`。
- 原用户计划 SHA `d3e95cfae617f03d602575f04b872a39b3da62e259c8b9902f147fd7871460ad` 不变。

Host 仍为原 Qwen3.6-35B-A3B-FP8／vLLM0.27.1／xgrammar0.2.3，embedding为原bge-m3。container/image/command/environment hash/HostConfig运行后均与运行前一致。没有改parser、thinking、context、输出4096或服务；JSON-action行为由适配器实现。原Postgres public Store、upstream tools、checkpoint和业务journal保留，各组使用新namespace及独立SQLite，真实请求并发1。Product Schema/API/权限/Canonical均未改变。

## 必要工程验证

[V0和打包回执](../data/manifests/milai-m1-v18-verification.json)记录8项集中测试，以及问题相关的增补断言：旧v17格式拒绝、精确采用、changed/retained/unresolved、旧证据不能完成、pending clear、task-ended例外、tombstone、无关revision、pending冷恢复/task隔离、新revision再次触发、完成请求和业务效果不重复。合法 unresolved＋业务调用可以执行；协议矛盾同响应工具零执行，程序没有判断温度/金额真值。

Ruff、受影响12文件mypy、默认core类型检查、Lab与tools边界、可选依赖收集和CI路径通过。包装声明新增v18锁后只build一次，R1 sdist内41源码及锁字节一致，无私密/运行文件。R2只有生成schema分支修复，未重复build；该旧包不是最终R2源码发布包。

原服务六分支probe全部通过（6次／5634tokens）；R2仅复查三个改变的calls组合（3次／2792tokens）。这些指定输出的结构检查不等于Host能自主选择、取证或完成重核。没有运行完整测试套件或大规模benchmark。

## 保留的R1失败与修复

R1 changed 首次输出 `task_ended clear + search_memory`，运行时拒绝 `DECISION_TASK_ENDED_WITH_CALLS`；尚无Basis、重核或公开消息完成。生成schema允许了运行时明文禁止的同响应组合。修复只从calls分支排除task_ended clear，answer分支和提示/运行时语义不变。

[R1失败清单](../data/manifests/milai-m1-v18-r1-failure.json)保留1次／915tokens／32embeddingtokens、原41文件源码快照、锁、冻结、trace和数据库。R2使用新空状态，同一已冻结数据与rubric；没有把失败费用清零。

## 最终R2的三个实例

| 实例 | 原定证据变更 | 实际终止位置 | 结论 |
| --- | --- | --- | --- |
| changed | X@1=4°C → X@2=8°C | 完成第1消息，第2消息无pending却声明retained完成，并拟提前record 4°C；协议拒绝 | FAIL |
| retained | X@1=8°C note A → X@2=8°C note B | 第2消息无pending却声明retained完成，回答4°C；协议拒绝 | FAIL |
| irrelevant | X保持8°C，未采用Y通知09:00→09:30 | 第2消息在critical_parameters内持续生成空白，4096输出tokens截断 | INCOMPLETE/FAIL |

三组第1条回复均声称已查明保存的指令，却没有调用search_memory；同时对空状态输出task_ended clear。程序因此没有Basis可触发重核。第2条实际请求的Decision Context仍为`current basis: none`，只有当前用户消息e0；fixture更新确已通过真实上游工具提交，但新正文没有自动注入。changed中的e0不包含温度，却被声明supports_value；retained声明contextual，也未取得任何温度依据。

changed的4°C调用只是被拒绝响应中的意图，**没有实际执行**，且它出现于用户尚未批准的第2消息。retained的4°C回答也因整体协议错误未被Agent接受。irrelevant没有完整JSON。三组都没有到达第3条批准消息、执行业务或建立有效Basis。缺少采用X的前提，所以irrelevant的“零触发”不能判为选择性控制成功。

[结构化结果](../data/manifests/milai-m1-v18-results.json)及[机制回执](../data/manifests/milai-m1-v18-mechanism-results.json)记录各组中断、原证据hash、Store操作与状态指标；raw Provider正文/SQLite保持ignored。

## 独立指标与不可推断项

| 指标 | R2实际值 | 含义 |
| --- | --- | --- |
| 完整机制实例 | 0/3 | 三例均失败，非业务准确率 |
| 公开消息完成 | 每组1/3，共3/9 | 每组尝试第2条后中断，第3条未尝试 |
| Host搜索／记忆操作／业务执行 | 0／0／0 | Store的4个seed＋3个update均为显式fixture origin |
| 接受的proposition／adoption | 0／0 | 不能声称proposition质量改善 |
| 请求前Basis占用 | 0/6 | 6次正常Host请求均无Basis |
| 接受回复后Basis占用 | 0/3 | 另2次协议错误、1次截断 |
| trigger／projection／completed／unresolved | 0／0／0／0 | 虚假retained声明不计完成 |
| 质量、label-like、supports_value覆盖、adoption有效性 | 均0/0，不可估计 | 不能写作0%标签或100%有效 |
| 独立State／reviewer／Judge调用 | 0／0／0 | 普通ReAct中同代delta＋answer/calls |
| 原非干预诊断、MERIT金额grounding与生命周期 | NOT_RUN | 前置条件未通过 |

原v17在exposed组有14个distinct状态、9个标签式状态及22/22机械采用，本轮没有接受状态，不能据此宣称标签减少或有效性提升。v17受控实例已实际执行旧4°C；本轮连初始采用都未建立，不能把提前中断视为相对改进。

原计划§35的特定条件**没有成立**：本轮没有实际送达revision_changed，也没有执行stale 4°C。因此本结论不是“通知后仍执行旧值”的复现，而是这版协议未能建立并驱动所需链。根据§34/40仍不支持M1'成立，停止该方向的本轮工作，不叠加字段、长提示、Attention、自动search、reviewer或业务值规则来救结果。

## token、存储与全部费用

| R2片段指标 | changed | retained | irrelevant | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 实际Decision Context输入tokens | 96 | 96 | 96 | 288 |
| 可解析decision_delta字段输出tokens | 195 | 118 | 27 | 340 |
| 声明completion字段tokens（均拒绝） | 10 | 9 | 0 | 19 |
| 接受completion字段tokens | 0 | 0 | 0 | 0 |
| 无法解析的截断响应输出tokens | 0 | 0 | 4096 | 4096 |
| Decision SQLite bytes | 45056 | 45056 | 45056 | 135168 |
| Decision应用写事务 | 3 | 3 | 2 | 8 |

Context按实际`m1_decision_context`原文计数并逐条确认在Provider请求中，排除原system prompt。固定M1_PROTOCOL另外每次263 fragment tokens，R2累计1578；全部已包含在总输入用量。delta/completion片段不作为额外账单相加；截断delta没有完整字段值，4096响应tokens全额计入费用而不伪造片段计数。SQLite事务只统计应用activate/apply/reject/trigger/project操作，不含建表、格式初始化、checkpoint、sidecar或Postgres写入；WAL均0。未测M1 CPU/单独延迟。

| 阶段 | 生成次数 | 输入tokens | 输出tokens | 总生成tokens | embedding tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1六分支probe | 6 | 4965 | 669 | 5634 | 0 |
| R1 failed changed | 1 | 822 | 93 | 915 | 32 |
| R2三分支probe | 3 | 2470 | 322 | 2792 | 0 |
| R2 changed | 2 | 1733 | 319 | 2052 | 73 |
| R2 retained | 2 | 1733 | 196 | 1929 | 92 |
| R2 irrelevant | 2 | 1733 | 4182 | 5915 | 70 |
| **全部v18** | **16** | **13456** | **5781** | **19237** | **267** |

[连续费用回执](../data/manifests/milai-m1-v18-cost-summary.json)：8次embedding请求，unknown=0，Judge=0，截断1次。R2正式费用为6次／9896tokens／235embeddingtokens，包含所有中断。原v17的101次／101810tokens／916embeddingtokens及更早费用封存在history，未清零。开发代理用量不混入实验Provider统计，本地vLLM未计美元价格。请求数少来自早停，不能声称整体省钱。

## 反思、限制与交付

代码可验证状态协议，不会替Host建立判断、选择证据或执行重核。第一轮暴露生成schema与运行时组合规则不一致，已做通用修复；R2暴露无依据的完成声明、未检索却声称查明，以及开放字符串/数组生成中的空白退化。没有证据把这些归因于某个具体解码器bug，也没有用复制目标JSON的probe替代自主轨迹验证。

当前实现保留为研究原型；下一步研究方向需重新选择，不能把新增Attention当作已具备可靠M1的自然延续。本轮交付包含适配器、三fixture、锁/冻结、窄测试/CI、费用/失败/结果和[复现入口](MILA_LANGMEM_M1_PIVOT_V18_REPRODUCTION_20260926.md)。回滚参考为v17 commit `9438d13`，旧DB需旧源码，不自动迁移。无新rollback tag、无Product改动，语义可靠性和自主协议遵循仍是明确未解决限制。
