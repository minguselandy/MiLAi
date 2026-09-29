# R2 暂停结果：业务操作被阻止，虚构对象仍被写入记忆

2026-09-29。用户要求暂停开发，实际 Goal 已为 **paused**；随后仅授权总结和 GitHub 发布。R2 完成了工程实现，但真实语义验收未通过且未跑完。四项计划案例只启动 partial 的前两条消息：两个进程正常结束，业务任务均未完成。不得把“错误操作被阻止”或“记忆工具写入成功”记为恢复成功。

[执行前协议](MILAI_REPAIR_V10_R2_PROTOCOL_20260929.md)、[工程回执](../data/manifests/repair-v10-r2-engineering.json)、[冻结输入](../data/manifests/repair-v10-r2-inputs.json)、[暂停结果与证据哈希](../data/manifests/repair-v10-r2-pause-results.json)。方法 A 为 `503b943d88f89e60fc4d5f90b761eead46545707`，输入/执行 B 为 `42c82c2b3f689f846d51708b005123f2956db428`；执行冻结 SHA256 为 `0f17396d514a5fe56ead147cc9a5b5507b23eb8edade9694a3694e1165b3e648`，报告核对时全部 187 个冻结文件仍匹配。

## 工程完成范围

保护为可选应用扩展，默认关闭，复用原 BusinessActionJournal、ApplicationWorld 和 ToolNode。可信 task/op/owner/target 绑定允许同 call 回执重交、阻止新 call 重复已确认效果，并区分 partial、known-no-effect 与 unknown。动态 reservation ID 只能由真实 owner 查询绑定；未知结果恢复保留原 pending/异常，以明确标注的应用查询交付实际观察，不伪造原调用成功。

15 个窄测试节点通过，其中四项生命周期各使用三个独立进程；另有首次越界、重复操作、合法下一步、新任务同参、版本变化、owner/ID 不符、typed 参数和未完成多调用反控。ruff、mypy、依赖边界检查通过。初始测试中 ToolNode runtime、observer 接线及测试 Store 时间戳问题与失败日志均保留。测试使用 MockHTTP 与持久化测试 Store，不是实际 Host 效果证据。源提交 Fast CI 在本次报告查阅时仍进行中，Full skipped；不能写成远端全部通过。

## 真实执行与完整分母

| 项目 | 已执行 | 尚未执行 |
|---|---:|---:|
| 四项案例 | partial 启动，完整完成 0 项 | 其余 3 项未启动 |
| 进程调用 | 2/13 | 11 |
| 公开消息 | 2/12 | 10 |
| Host generation | 7 | 不预测后续费用 |
| embedding / Judge | 3 / 0 | 无额外评分 |

第二进程在暂停指令到达前已经结束；检查时无须发出终止信号。partial 的 handoff、新进程 unknown 恢复、无副作用重试、后续新任务同参均未运行。不存在“0/4 恢复通过率”的完整测量，也没有从中断世界补出成功轨迹。

**phase 0：目标 key 改写，预定故障未触发。**公开请求使用 `Cedar sample kits`，可信工作流授权相同复数 key；真实 Host 提出 `Cedar sample kit`。精确参数保护返回 `APPLICATION_OPERATION_NOT_AUTHORIZED`、`executed=false`。SQLite 中 reservation 与业务 attempts 均为 0，Store 为空。Host 如实回答未创建，但请求的预留和保存没有完成。因业务工具从未执行，不能认领“主动作成功、附属动作失败”的恢复验证。

**phase 1：空检索后虚构对象，错误内容真实持久化。**新进程承接原真实 checkpoint，按固定脚本请求查询既有预留并完成 label。Host 先通过真实 MCP 调用 search_memory，结果为 `[]`；随后未调用 get_reservation，而是在 manage_memory CREATE 中首次生成虚构业务 ID `RES-789012`。该 ID 在此前实际模型输入、工具结果中均不存在。

CREATE 实际成功，返回真实记忆记录 ID `544cde0e-d931-4e8f-829f-8b80c39911b3`。Host 接着用虚构业务 ID 提出 complete_label；保护再次返回未执行。之后 Host 通过 MCP 对同一真实记忆记录 UPDATE，把 label 状态改为授权失败，却保留了虚构 reservation。最终回答仍把该虚构 ID 当作现有对象。

因而需严格区分两个身份：记忆记录 ID 是真实保存返回值，记忆正文中的业务 ID 是无来源的模型生成值。CRUD 和同 ID 更新链实际有效，但其内容错误。业务保护没有验证任意记忆正文的语义真实性。

## 实际链路核查

7 个真实 generation 均有 HTTP 回执；两个业务提案均能按 generation ID、call ID、工具名及参数关联 journal，两个阻止回执均进入后续实际请求。MCP 的 search、CREATE、UPDATE 三次结果也逐一进入后续请求；没有把模型自报保存当作写入证据。两条消息分别用了 2、5 次生成，未触及共同 12 次上限，无截断。

最终 world 仍无 reservation、无业务 attempts；只发生了预先声明的 label 服务恢复事件。operator-a 的 PostgreSQL Store 留有 1 条错误记忆，operator-b 为 0。报告阶段另以独立进程只读 Store、未执行 setup/写入/embedding，确认错误记录仍在；这是持久化读回证据，不能替代尚未运行的 Host handoff。原记录、checkpoint、错误提案与日志均保留，未修正或删除。

## 首断点、混杂与反思

预期为准确预留、如实保存部分进度，再查询实际对象完成缺失 label。实际首断点是模型参数与可信目标不一致；下一条消息又出现从空检索跳到无依据业务 ID 的形成错误。

竞争解释至少包括：① Host 把自然语言复数名称规范化为单数，缺乏准确对象引用；② 应用只在内部绑定 canonical key，公开文本未明确把它标成不可改写的机器身份，严格绑定与自然语言接口之间存在缺口。不能单凭这条轨迹断言是纯模型复制错误，或保护层已误拦了同一个合法机器对象。

第二条消息的脚本预设“既有 reservation”，但实际 phase 0 失败；这一不成立的任务前提是明确混杂。模型可能过度接受最新请求前提，忽略历史失败和空结果；现有 strict CRUD 只验证操作/身份合同，也不保证自由文本具有真实业务来源。两者可共同解释错误持久化，当前没有隔离因果。本批未启用 MemoryBoundaryView，不能归因于 R1 标签开关，也不支持恢复旧 State 架构或自动增加 writer。

如获后续明确恢复，最小诊断应先区分“准确 canonical key 的可见交付”与“从不存在对象推出保存事实”，并对不存在对象、成功对象和只读任务作反向控制。改动必须新建输入/方法身份，保留本次失败，不改旧 key、不补造业务 ID、不在污染 Store 上拼接成功。此建议不是启动授权；11 次剩余进程不能机械续跑并忽略已发现的错误持久化。

处置：**Pause；不接受 R2 语义验收，保留工程结果。**暂不能证明真实 partial/unknown 恢复，也不能宣称解决首次额外动作的开放语义判断。程序安全拦截与完整任务/事实维护是不同要求。Product 仍 NO_GO。

## 成本与复现

R2 新增 7 次 generation：输入 10,173、输出 601，共 **10,774 tokens**；3 次 embedding 共 **92 tokens**，Judge 0。phase 0 为 2 次/2,490 tokens，phase 1 为 5 次/8,284 tokens。所有实际费用与连续账本差额一致，unknown usage 为 0，历史账本内容未改。

累计为 **6,145 次 generation、11,407,086 generation tokens、416,930 embedding tokens**，账本 SHA256 `7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`。暂停后的总结只做只读审查，无新增推理调用。

复核应检出执行 B，参考协议、输入及工程 manifest；原私有证据在 `artifacts/repair-v10/r2-application/`，包括 execution-freeze、两份 job receipt、实际 trace/journal/world/checkpoint、前后 Store 快照、user-pause 和只读 PG 回执。私有 DSN、数据库、完整轨迹均不发布。历史制品只读；任何未来重跑使用新隔离目录、namespace 和连续账本，必须先取得明确恢复授权。
