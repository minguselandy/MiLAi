# Host 快照时点 R1：首响应诊断

状态：`COMPLETE_READ_ONLY_DIAGNOSTIC`。源码
`83b707edee01435db454493ee792ca73f9de531f`，按
[冻结协议](../data/manifests/local-state-attention-host-snapshot-r1-protocol.json)
运行六次独立首响应调用；[精简结果与哈希](../data/manifests/local-state-attention-host-snapshot-r1-results.json)
保留全部输出分类和费用。没有执行工具、读取/写入 Store，也没有完整任务成功分数。

原断点是维护输入 R1 的第二次合法增量：维护已正确将 3 改为 4；首次新会话 Host 请求只有
system 与当前 user，尚无旧助手“5”，但 Host 将 4 再加为 5。

| 视图 | 两次首响应 | 解释范围 |
| --- | --- | --- |
| 原视图，完整请求相等 | 都提出 manage_memory(update) 写 5 | 原错误在这两次请求重复出现 |
| 原 State4 + 时点/当前来源身份 | 一次提出写 4，一次直接回答 4 | 与快照时点/来源副本歧义解释相符 |
| 真实维护前 State3 | 两次都提出写 4 | 支持基准混淆；仅为诊断，不是 live 架构 |

三个视图保留原 system 前缀、全部真实用户消息、schema 和模型参数。原视图两次实际请求
与原 trace54 的请求对象/字符串完全相等；其他变体只改既有 work-view。
时点候选添加程序事实：当前 user source ID、本次维护输入的 source IDs、after-maintenance
时点、pending IDs；配一条通用说明。它不声称观察过的事件已经语义正确应用，不从引用或
机械依赖推导事实正确性。元数据与说明是一个组合候选，本诊断未拆分各自贡献。

竞争解释 H1 是 post-event State 被当作当前指令前基数；H2 是相同文本的历史事件、当前事件
及其展示副本关系不明。本批输出支持这个边界值得研究，但没有区分 H1/H2 的全部贡献。
更不能将首次错误归因于尚未存在的旧助手“5”；后续 trace76 确实另有错误助手/普通 memory
影响，仍是不同断点。

直接回答“4 已记录”时，真实 LSA State 在原场景中已经持久化为 4；这不代表本次 probe
执行了原生 LangMem 更新。另五个输出都是未执行的 memory 提案。没有补发下一轮来挑成功
轨迹，也没有把正确中间参数换算成最终副作用验收。

新增 **6 次生成 / 8,062 generation tokens / 0 embedding tokens**，全部为 Host，unknown=0，
实际 HTTP 共 5.088s。连续账本为 **2,418 次生成 / 3,019,268 generation tokens /
18,183 embedding tokens**；历史链保持不变。只读 probe 不经过新原生工具条件参数 guard，
不能用此次结果声明该 guard 带来语义收益。

24 项相关源码检查、/tmp prepare 和一次必要构建沿用先前记录；实际六 job 的 prepare、
source/input/参数、请求相等性、返回 usage 与 ledger 均核对。复现用该提交与固定 ignored
输入，通过原 `run_local_state_attention_read_probe.py prepare` 和按协议顺序的 `run-job`；
使用新运行目录，runtime 不读 rubric，不执行返回 calls。

Continue 仅指进入[不改措辞的正确性反例](../data/manifests/local-state-attention-host-snapshot-r2-protocol.json)：
旧/漏改 State、真实 tool-only 回合、已发生的错误业务回执。必须避免把时点说明变成 State
可信标记，或让计划值覆盖真实 side effect。live Host 视图尚未改变；六次首响应不是稳定收益、
未见验证或整个 Goal 完成。若反例仍错误/不确定，则停止本轮候选部署与措辞迭代，继续 LR、
强历史基线和后续计划，并保留 Host 限制。Product 仍 NO-GO。
