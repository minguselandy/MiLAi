# v13.1 scope R4：形成门禁失败

日期：2026-09-30。原规划 ACTIVE，reader 两组均 NOT_RUN。

[协议](../data/manifests/v13-1-scope-r4-protocol.json)要求先有正确 scope bank，再比较相同 bank
上的 reader 消费；原指令与通用“问题不等于确认、保留适用范围”指令已分别冻结。
实际形成只有原始第一条公共消息，没有未来问题。结果的 team/body/episodic 保留，但 Host
把用户的“本周”写成 `time_limit=2024-05-20T23:59:59Z`。原始来源没有该绝对日期或时间锚点，
实际 SourceEvent 捕获日期为2026-09-30。原始提案与错误 scope 均真实持久化，不事后修改。

[失败证据和成本](../data/manifests/v13-1-scope-r4-results.json)记录最早断点为形成提案，
所以停止 reader 比较。不能把“团队范围尚在”说成完整 scope 正确。Root 的脚本初检只要求
scope非空，曾过早写了“正确”判断；完整值检查立即发现错误，在任何 reader HTTP 前否决。
初始 bank-freeze、两个复制件和原代码零HTTP prepare保留，本结果明确覆盖初始判断。

新增2generation/2214tokens，embedding0、Judge0、unknown0，逐响应与原ledger一致。
连续6193generation/11472393 generation tokens/416930 embedding tokens，完整I/O仍未测齐。
没有重新形成到通过或偷偷清理日期；正常24分母与原R1失败保持。

下一最小实验 R5 仅加通用相对时间指令，与原指令在相同源/模型/工具/空 bank 比较。
候选仍造日期或丢团队 scope 则不能通过；仅当合法实际 bank 存在才开展独立消费诊断。
这条提示可能足够，届时收缩结构创新主张。Product NO_GO。
