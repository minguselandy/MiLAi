# P3 六模板 G/L/LRU 匹配比较

状态：`CLOSED_WITH_ONE_ABORTED_TRAJECTORY_AND_SEMANTIC_FAILURES`。
按[预注册协议](../data/manifests/local-state-attention-p3-matched-r1-protocol.json)，
六个 development 模板 × G/L/LRU × 两次完整重复，保留 **36 轨迹 / 234 消息**分母。
35 条轨迹完成；LRU 第二次高耦合轨迹首消息中断，其后五消息未运行。
共 228 条消息完成、一条尝试失败、五条未尝试，不能写成 36 条全部完成。
[精简结果与证据哈希](../data/manifests/local-state-attention-p3-matched-r1-results.json)
包含逐消息失败理由、实际 HTTP/Store 计量、输入和原始结果哈希。

全批源码 `3f155f5213d1ee8f3a594324e3ffe2b4b4fafbb2`，方法实现与前次
`eda7add22d3a78f6074098c800fad36707ed7dd2` 相同；143 个实际 source 文件哈希一致。
两次重复使用独立 namespace、world、checkpoint；每 phase 独立进程，真实 HTTP 并发 1。
保持原 Qwen Host、2048-token 控制器、4096-token Host、13/12 次每消息容量、65536 上下文、
temperature=0、thinking=false；未修改 vLLM。输入、rubric、顺序和源码均未在批内改变。

## 任务结果与严格口径

| 方法 | 严格消息 | 完整轨迹 | 完成消息 | 生成次数 | 生成 tokens |
| --- | --- | --- | --- | --- | --- |
| G：单工作笔记 | 60/78 | 2/12 | 78/78 | 234 | 414,859 |
| L：局部 State 全读全维护 | 60/78 | 3/12 | 78/78 | 246 | 354,030 |
| LRU：候选维护、独立读取 | 59/78 | 4/12 | 72/78 | 442 | 472,853 |

| 模板 | G 第一次、第二次 | L 第一次、第二次 | LRU 第一次、第二次 |
| --- | --- | --- | --- |
| 原交错/后台更新 | 5/6、5/6 | 6/6、6/6 | 6/6、6/6 |
| 原部分失败/双 owner | 4/6、5/6 | 4/6、4/6 | 4/6、4/6 |
| 共享政策/适用范围 | 4/7、5/7 | 5/7、5/7 | 5/7、7/7 |
| 等权来源冲突 | 5/7、5/7 | 6/7、6/7 | 6/7、5/7 |
| 用户报告闭合/重开历史 | 7/7、7/7 | 7/7、5/7 | 7/7、6/7 |
| 高耦合/共享容量 | 3/6、5/6 | 3/6、3/6 | 3/6、0/6（中断） |

评分遵守冻结的逐消息 rubric：请求的事实和真实业务动作全部正确才通过；acknowledge-only
不要求枚举全部事实。实际业务 key、目的地等按精确字段；共享包装允许同义表达，但外罩与
红色封条两部分都必须保留。仅大小写/限定词失败与数量、共享容量、来源权威错误分开解释。
例如 LRU 重开第二次的实际 `Desk A-9`/`Flat folders`，及 G 高耦合第二次的 `Bay B-3`，
对应消息仅因精确大小写失败；后者数量 3/4/3、合计 10 和三次真实行动均正确。
不能在看到结果后放宽 rubric，也不能把这些失败描述成错误数量。
冲突模板两次 book-only 回答夹带 panels 内容仍计指令范围失败。

六条部分失败轨迹均实际 get found，并沿最初真实 reservation ID 补 label，没有重新预约。
初始/第二 owner 的单复数、缩写或 slug key 错误继续计失败；正确恢复不能追补错误初始动作。
同 session 的 business_calls 是累计记录，审查按 journal call ID 去重并核对 world attempts。

## 首断点与竞争解释

**重复增量。** Expected：一次“各加一”使 2/3/4 变为 3/4/5；之后普通记忆工具回执不应再加一。
Observed：高耦合第一次三臂、L 第二次都在后续报告出现 4/5/6，继而形成错误组合计划。
G 第一次实际 trace 第 7 行控制 HTTP 正确写入 3/4/5；第 12 行 pending 只有
`manage_memory created` 工具事件，输入仍携带原“各加一”的 `current_task`，输出变成 4/5/6。
这些内容被持久化并进入后续 Host HTTP，不是评分器推测。

H1：原用户事件重复入队/恢复重放。该局部 HTTP 中没有第二条用户 pending，反对此解释。
H2：可写维护反复看到已消费的任务文本，将其再次作为状态变化依据。实际输入和编辑支持 H2。
首断点在维护输入边界与模型更新；LRU 使用 edits-only 输出仍传入 current_task，未真正隔离。
G 后续 State 一度恢复正确 3/4/3，Host 却沿自身旧回答行动为 4/5/3；这是另外的 Host 历史混杂。
不能预先宣布维护输入修复能解决全部最终动作错误。

**背景事实与共享政策丢失。** G/L/LRU 都有具体包装被省略、相对措辞替代明确值，或封条条件
在新 session 消失。L 第二次 shared 最终旧计划仍写“未应用包装变化”、未预约，同时新卡记录
实际错误包装的预约结果。LRU 第二次 shared 任务 7/7，却留下两张重复确认卡和一张过期未执行卡。
H1 是 U/A 漏选；H2 是正确候选进入维护后内容/引用不足，或 Host 未消费已有正确证据。
不能把所有丢失都归因于选择器：G/L 全量机会也发生，旧 R3 已有正确 U/正文仍丢包装的精确证据。
本批不再加措辞补丁；后续 LR 与固定 bank 的 U/A 诊断才适合区分选择和维护问题。

**初始空形成。** L 第二次 reopen 第一实际控制结果为 `edits=[]/focus=[]`，合法 no-op 消费初始
事件；后续历史问答缺旧数量/包装，最后缺 appointment。H1 是持久化或读取失败；H2 是模型未形成。
实际空编辑先于写入，支持 H2。pending=0 不能说明事实形成成功。

**可选工具参数异常。** LRU 第二次 coupled 首次 Host 请求
`manage_memory(action="update", content=...)`，漏掉 ID。安装的 LangMem SDK 在 namespace/write
之前抛出 `ValueError: You must provide a MEMORY ID when deleting or updating a MEMORY.`。
应用只隔离原公开消息容量异常，此 ValueError 终止整条轨迹。H1 是 Store/服务故障；H2 是 Host
参数错误加可选工具错误观察缺口。实际 HTTP 漏 ID、SDK guard 的位置、空 LangMem namespace
和零业务 side effect 支持 H2。已生成的 LSA State/事件保留。

原 driver 遇错立即停止。Root 只读诊断后，在继续前冻结 continuation-decision：该条终结为
0/6，不重试、不补后缀、不替换；用原顺序、相同源码完成四条尚未开始的独立轨迹。
这次显式继续决定、停机 ledger 和失败快照哈希均保留。不得宣称批次无中断或隐藏此协议执行说明。
故障轨迹成本为 3 次生成 / 1,914 tokens；诊断没有模型调用，额外两次只读 Store 检查。

## 成本和机制覆盖

本批新增 **922 次生成 / 1,241,742 generation tokens / 6,173 embedding tokens**（65 次 embedding）。
控制 568 次/590,235 tokens，Host 354 次/651,507 tokens，unknown=0。
连续账本达到 **2,304 次生成 / 2,876,194 generation tokens / 17,335 embedding tokens**，
历史成本链保持不变；历史 SER exact-version reads 107 不与 LSA get 混为一项。
真实 HTTP 用时控制 766.804s、Host 262.022s、embedding 3.253s；不是端到端运行时间。

| 方法 | 控制 calls/tokens | Host calls/tokens | embedding tokens | 最终 LSA 逻辑 value bytes |
| --- | --- | --- | --- | --- |
| G | 117 / 178,529 | 117 / 236,330 | 2,075 | 95,575 |
| L | 123 / 159,619 | 123 / 194,411 | 2,071 | 90,746 |
| LRU | 328 / 252,087 | 114 / 220,766 | 2,027 | 104,511 |

LRU 控制细分：U 100 次/44,763 tokens，维护 114 次/156,406，A 114 次/50,918。
实际维护候选正文 44,976 chars，相应全 bank 正文 65,094 chars，比例 69.1%；目录还产生
31,086 JSON bytes。总生成 tokens 却为 L 的约 1.34 倍、G 的约 1.14 倍。
候选正文缩减没有在此小 bank 上转化为总成本优势；三臂实际工具循环不同，不能把总差异
等同于表示压缩或 U 的独立因果效果，LRU 还有一条早停导致的少执行成本。

运行内 BaseStore get/search/put：G 2068/1183/473，L 1824/1240/486，LRU 2082/1037/500，
失败均 0。它们是 Python 公共 API 操作，非 SQL round trips。目录仍读取完整 State 记录。
另计 Root 空 namespace 检查 72 次、已完成 phase 快照 70 次、故障诊断 2 次只读操作。
逻辑 value bytes 不含数据库物理开销；每条运行的 SQLite 文件 bytes 与 Store CPU/wall/字节
统计保存在精简证据中，不能称总数据库占用。

354 个 State 视图按事件顺序绑定真实 Host HTTP；897 次原事件展开正文与 scoped Store 原值一致，
没有来源 missing/deleted/invalid/预算省略。G/L/LRU 来源激活视图分别 93/73/96；显式引用合法
不代表足够或语义支持。L 有两次 skipped_invalid_edit/degraded，pending 先保留、后消费；其余
无控制退化，最终 pending 均 0，无模型容量/服务错误。最大实际交付正文仅 1,913 chars、4 卡，
未检验 16,000-char 上限、稠密大 bank 或 selector 的规模边界。

## 决策、下一切片与复现边界

Continue / Simplify：当前结果没有建立稳定的 LRU 质量或成本收益；保留 G 强基线和全部失败。
先做一个通用输入边界修复：所有可写维护只接收 pending 事件与候选 State；U/A 和 Host 保留
current_task。G/L 全读分支可复用 edits-only 维护，不增加无用 A 调用；legacy focus 分支显式兼容。
不新增已处理事件账本，不按文本去重，不同时改 Host 历史、参数或业务 schema。

必要零模型反例：新用户增量进入一次；后续普通工具回执没有重复任务提示；不同来源 ID 的相同
真实增量仍有效；部分成功回执仍可维护；前台读取与后台更新各有输入。随后只冻结三臂各一条
原高耦合完整轨迹，加少量新同文本事件反例，验证请求边界和实际行为。旧污染 bank 不用来声称修复。
可选 LangMem 缺 ID 应另作局部错误观察切片，不能宽泛捕获所有 ValueError 掩盖数据库错误。
不把下一版结果与本版拼为纯表示消融，也不立即重跑全部 36 条。

该批可按协议 run_order，在上述提交使用 `tools/run_local_state_attention.py prepare`，再按
同一 `--config --script --run --arm --repeat --runtime-root` 和 prepared 文件逐 phase 执行
`run-phase --phase 0`、`run-phase --phase 1`，每次独立进程。config 只注入本机 tokenizer 路径，
私密 DSN 通过环境提供；新复现须用新 run ID/namespace，并沿自己的连续账本计费，不能重放已有
业务数据库。运行器生成 manifest，Root 离线 rubric 审查；runtime 不读本结果、rubric 或 gold。
原失败轨迹只能按其历史证据复核，不能用后来成功重跑替代。

已通过的源码窄测和必要构建没有为此次报告重复运行；本轮检查实际身份/输入、HTTP→Store→
后续视图→回答/行动、source 字节、成本与哈希。两次重复、六个 development 模板、单一模型族，
不作 unseen、统计显著性或泛化结论。P4–P7、强历史基线、真实授权删除、物理归档/重激活、
共享原子组、未知结果恢复、第二任务族/模型与完整 Goal 仍未完成；Product 继续 NO-GO。
