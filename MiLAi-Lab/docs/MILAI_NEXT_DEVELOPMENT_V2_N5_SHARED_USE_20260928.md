# v2 N5 / X5：共同记录接口下的连续使用

状态：**冻结六条命令已完成；存在语义失败，G3未通过。** 详见[N5/WP7结果](MILAI_NEXT_DEVELOPMENT_V2_N5_RESULTS_20260928.md)。原执行前协议按方法提交1d7460b复现。
依据[v2计划§11–15](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v2.0.md)，接续[N2](MILAI_NEXT_DEVELOPMENT_V2_N2_RESULTS_20260928.md)与[N3](MILAI_NEXT_DEVELOPMENT_V2_N3_RESULTS_20260928.md)，覆盖连续原生任务、明确构造的缺项与WP7费用。
不将短只读/单提案分数改名为生命周期验收。

## 方法收缩与首断点

N2未显示独立A收益，N3全候选已满足两个前缀且最便宜，因此本轮不保留独立A/U调用、自动维护或N4反馈。
仍需回答：从空库在线形成后，预先交付State正文是否帮助后续实际业务，或抵消费用。
竞争解释H1是预交付减少重读/误用；H2是完整合法历史与共同普通memory/READ已经足够，额外State正文只增加输入成本。
本轮不预设Host双库写入或State配方优越。

首个实现断点是原MERIT runner只装配普通LangMem Agent，而现writer view与full_history互斥且夹带ordinary/source呈现。
可能只是缺共同history/tool接线；也可能现有比较把多个呈现差异捆在一起。必须先解决这两个机械边界，再运行。
Root向Astra提出这个具体设计冲突并完成一次局部设计分析，由同一Sol负责人收敛实现；不设置常驻审计者。

| 条件 | 共同部分 | 唯一区别 |
| --- | --- | --- |
| H_shared | Host拥有strict ordinary memory＋State完整工具；真实业务工具、read_history、完整已访问owner历史、ordinary正文、来源目录和State目录 | 不额外预交付State正文，仍可主动READ |
| all_shared | 同上 | 每次请求预交付当前全部State正文 |

这不是原生B1方法复现，也不是“有无State工具”消融：H可以自然创建和读取State，旧State工具回执仍可存在合法历史。
共同双库工具可能有认知/schema成本；结论只适用于此共同接口下的差异。
State和ordinary均从空初态形成，允许零写入或只用一种表示，不要求每件事复制两库。
明确长期约定仍须有持久可用记录；实际存在的任一记录错误或过期不能被另一库正确掩盖。

两臂自然分叉后各自保持实际行动、来源、ID和记录，不跨臂复制回执或形成好的bank。
原消息字节、模型参数、来源/owner权限和业务工具一致；不按gold、任务ID、订单/金额或预期答案修正模型。

## 原生任务与构造补充分开

先运行MERIT arc3-000完整五episode、七公开消息，两项dependent reuse。
原external source commit为 `293933d96b1d1849e1f20d1bb324def5de9ed33f`；
arc SHA256 `2589ab3113e8617beb6960410d936da71b30e39ba4871adf66f72a488373bfba`，
初始world SHA256 `0a574e9ccb44fb4d3ae4fc1c4cb4692a3837c3dbf739f71c14070f008e3dba43`。
Root已只读核对12个原源码文件与两个制品；prepare还须使用既有load_frozen_arc重建核对。
这是早已暴露的v23第一条完整arc，不再沿用旧manifest“unseen”状态；新selection明确EXPOSED。

原task.user_messages、顺序、business tools/SQLite world及原生checker不变。
使用原生任务与checker上的适配Agent，memory/State跨episode保留、checkpoint按原episode分开。
既有memory_had_fact仅识别原search_memory，不改其口径；State READ/delivery另列辅助事实。
原world若没有跨owner授权语义，本原生单元不承担该项验收。

补充使用已有user-scoped ApplicationWorld；两臂从空记录/空业务世界开始，label service unavailable。
原11消息未执行草案仅作参考，精简为八条新冻结的构造开发请求：

1. Riley明确长期2/S-2/fiber cases计划；没有预填正确记录。
2. Noel独立长期5/M-4/foam inserts计划。
3. Riley正确复用，仅本次回复以TEMP开头。
4. Riley当前仍总结原计划，同时保存独立D-2/11:45提醒；不得把TEMP变成永久默认。
5. Riley授权删除saved reminder record，保留handling plan；明确不删除对话历史。
6. Riley真实reserve_and_label一次，保留实际预约、标签失败、实际ID，不重试。
7. 新进程、新session读回真实预约与原ID/状态，不重复副作用。
8. Noel再次复用自己的计划和无预约事实，保持owner隔离。

前六消息为phase0，后两消息为phase1；各消息为独立session，完整已访问owner历史仍按相同规则可见。
先完成两个原生单元，再按H phase0→all phase0→H phase1→all phase1执行，每个命令新进程、真实HTTP串行。
各arm/workload隔离namespace、Store、checkpoint和业务world；相同arm两phase保留自己的状态。
不因某臂失败替换样本、改顺序或给额外修复机会；保留容量失败/跳过及实际终点。

## 历史、来源、退出与恢复合同

Archive-access表示真正内联合法已访问历史，不只是有一个理论上可调用的history工具。
复用公开checkpoint和HistoryAccess；native回调只登记公开owner/session/index/status/访问顺序，
不能把含before_world/checker/gold的私有进度文件交给Host。
先对当前真实checkpoint收集观察，再投影跨session历史，避免把借来的历史重复摄取为新事件。
普通记录、source catalog与State目录共同呈现，只有额外State正文开关不同。

每个公开回合独立记录Host终态、实际ordinary/State/pending、业务回执/世界和费用。
成功Host的ack仅表示处理过，不能认证语义正确；失败pending保持真实状态。
N3的缺evidence_refs案例仍保留，不在N5程序中自动补引用或改写成已解决。

本构造退出只要求删除已形成的saved reminder记录，精确目标、保留handling plan；未形成不能通过“无可删”冒充完整退出成功。
不调用source forget，不擦除原checkpoint；archive仍可能包含原提醒，不能宣称物理遗忘、原来源清理或全链删除。
未来若从历史重新创建已撤销提醒，应记为退出失败，不静默抑制历史以修分。

恢复边界是已闭合公开回合/checkpoint后的进程重开，验证真实业务副作用和ID复用。
若phase0先发生容量/基础设施失败，按实际边界和缺失覆盖报告，不能称已经闭合。
BusinessActionJournal保护已知业务回执；普通memory/State CREATE不具任意写后崩溃exactly-once保证。
本轮不增加事务/journal层，也不伪装随机硬崩溃或在ToolMessage持久化前被kill的验证。

## 输入身份与评分

目录：[next-development-v2-n5-shared-use-r1](../data/diagnostics/next-development-v2-n5-shared-use-r1/)。
运行器只读config及相应workload inputs/selection，不读rubric或execution-order中的评分信息。
Root依据后两者编排与离线评分，正式源码发布后将所有身份绑定execution-freeze。

| 文件 | SHA256 |
| --- | --- |
| config.json | `954332a44d0ebf2f02551a253448b80b53ded60fe78fe01f88aa56dde4bf018b` |
| merit-inputs.json | `0fe814f8ba9ae81937d48ccf1993c6bed29e466f49ad4898f37b3e8497ee4944` |
| merit-selection.json | `a8ec24d804e5b37ab15ef1442025ae8e41198b397efb55090a0b71755a13a425` |
| application-inputs.json | `4e2736127d12e667ca39e6baae7e26c57225f735e537b1cba62185b5bb4539ea` |
| rubric.json | `400324751ce37dad786007edde20f3c69d02eb8d2b6c84eb4b7ef975c5a3b5e2` |
| execution-order.json | `01c8636668eaff22c694b051ddd2ba77341fe501505609787eb76dd82584fab5` |

原生strict/checker、Host完成、必要维护、各库实际内容、真实行动与自然语言忠实分别报告。
构造补充按八条冻结rubric逐项验收；原生分数不与构造分数拼成总样本或总成功率。
每臂仅一个已暴露arc/一个构造owner组，不作显著性、unseen或通用优越性结论。

## WP7费用与门槛

所有真实generation按provider request ID去重。本方法预计只有task_host调用；同一请求包含语义写入与业务时只计一次，
不再按逻辑角色把它重复归作维护调用。embedding、失败、空提取、重读、来源/历史投影和观测开销全部保留。
共享服务不变，Host每公开消息12次、4096输出、temperature=0、thinking=false、容量65536。

原生按公开交互阶段归属：episode0/1为前期任务与形成，episode2维护，episode3/4复用。
这不是声称前期全部token只用于记忆形成；逐请求/逐episode费用仍列出。
R=1、2为dependent复用机会，展示累计付费/实际阶段，以及最终总付费除以2；另给每五个原生episode费用。
构造按formation（1/2）、maintenance（4/5）、use（3/6/8）、recovery（7）互斥归属；
R为3/4/6/7/8五个计划复用机会；第4条混合维护与总结，其费用只归maintenance一次，但仍算一次复用。
正式执行冻结前核对发现初稿漏计该次总结，已把R由4改为5；旧未执行rubric保留在ignored准备制品。
输入、方法和阶段费用归属不变，失败也留在计划分母和成本中，恢复只加一次。

两种任务的完整成本分别报告；不能从固定bank或漏维护获得“20%生命周期节省”。
Store逻辑字节/调用、测得的局部CPU/HTTPwall与完整端到端时间区分；未测物理I/O、全进程CPU、美元/GPU小时保持unknown。
权威账本沿用原artifacts/ser-v20/budget.json；N3终点2830 / 3512213 / 20093，正式执行以实际起点快照为准，不清零。

有可解释质量/全周期成本信号才评估N6资源条件；否则收缩或停止当前State优越性主张。
N4不是前置，第二模型/新部署/训练/大规模扫描不自动触发。Product仍NO-GO。

## 工程准入

[公开检查回执](../data/manifests/next-development-v2-n5-checks-20260928.json)记录最终38项受影响窄测、Ruff、六源码Mypy、实际CI归属矩阵及两项边界通过；四份零模型prepare绑定各155个源码身份。
一次入口构建与24项包内容核对通过，早期格式/类型/检查脚本问题保留。源码不再修改；此处状态文字在包测量后更新，不为文档重复build。
这些是Mock/本地SQLite工程证据，真实Host/embedding/shared Postgres调用为0；不提前授予语义通过。

本批实际结果：两原生单元各5/5；构造生命周期各0/1；所有State为空，不能归因正文预交付效果。新增51生成/138109tokens/63embeddingtokens，N4/N6未触发。此处事后状态更新不改变原冻结输入、rubric或顺序。
