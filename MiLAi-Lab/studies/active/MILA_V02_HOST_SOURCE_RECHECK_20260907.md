# SIM07：Host冷启动一次来源回查

状态：`OPEN_DEVELOPMENT_HOST_MANAGED_E2E_FIXED_ASSERTIONS_PASSED`。
本例公开保存、独立冷恢复、相关来源实际进入模型请求及首次最终交付的固定必要条件
均取得证据。它是已打开任务上的Host触发开发验证，不授予D4/D5或泛化通过。

此前SIM05的普通搜索可用、SIM06的覆盖提醒实际呈现，但Agent都只确认了记忆已有项。
随后零模型的公开诊断直接用完整任务原文作`milai_memory_resolve`查询，0.634785秒，
第一条即返回遗漏的原始用户报告。没有添加答案词、重排来源或改写记忆。

据此实现可选`host_source_recheck: CURRENT_TASK_ONCE`，默认OFF：仅续做A/B在首次
模型发送前调用现有公开检索一次，G不触发，查询不经额外模型加工。Agent仍可自行检索、
直接读文件、继续查询或不保存。原始返回与warning保留，声明引用在进入/重新进入上下文
前核验；取得和呈现分别记录，调用耗时属于会话deadline，全部输入计入累计token。
不新增Runtime接口、State字段、Hint planner、Judge或Canon治理变化。

配置`configs/v02-local-sim07-host-recheck.json`；产物
`artifacts/v02-e2e-generality/sim07-host-recheck-20260907a/`。
与SIM05授权配置比较仅execution_id及host_source_recheck不同，未采用SIM06的提醒。
Product pin为`cdccd06328cd07eb77c2fc3956c3df742c30b2c38ae5aa7ee65a7d3c31c30c5c`。

沿用SIM04真实G的details/handoff和完整44文件，所有字节哈希一致，G没有再次调用模型。
两个新项目公开导入并核验来源，484个引用分别重绑定；公开保存回执与head关联。A/B
新进程恢复到各自不同State身份，初始文件manifest相同；A预载L2，B未预载L2。

| 观察 | A 详细预载 | B State优先 |
|---|---:|---:|
| 模型请求 | 3 | 5 |
| raw input | 103,876 | 165,208 |
| output | 228 | 416 |
| raw合计 | 104,104 | 165,624 |
| 在线秒 | 31.550509 | 44.063370 |
| Host公开回查秒（已含在线时间） | 0.581348 | 0.543378 |
| 固定必要条件 | PASS，2件 | PASS，2件 |

两组最终都正确计入一件待取的海军蓝外套和同一双Zara换货靴子，没有把重复提及或两只鞋
计成更多物品。A读取session-011/030；B继续分页读取session-030后交付。观察边界为实际
最终交付文件，之前动作只有只读来源访问，没有更早的错误实质行动。整体文章质量、所有
历史理解完整性及来源之外的事实不在本次判据中，不默认PASS。

关键原始用户句子在A-001、B-004（分别为两组首请求）的message 2、字符偏移414处出现，
长度110字符。请求正文SHA与预约一致，Provider回执身份、input/output usage均对应。
因此本次不止“检索返回过”，还确认关键来源确实进入模型输入；完整证据在terminal-audit。
检索返回仍DEGRADED，并不意味着所有历史都已覆盖；这个warning保持在实际输入中。

**本例State优先反而多61,520 raw tokens（+59.09%）。** 两组虽然正确，不能据此采用
State-first作为降本默认。共同G历史成本337,584 raw tokens不重复计费，但讨论完整链
开销须列出：G+A+B为607,312 raw tokens；共同产物的生成/维护成本没有被当成免费。

新增批次8请求、269,728 raw tokens；准备36.657658秒，全批115.606323秒。pending/违规0，
无付费、Judge或隐式重试。API/worker/两个模型进程已退出，PG停止无OOM，共享服务不变。
累计SIM01–SIM07为53请求、1,159,327 raw tokens，所有失败和本例G复用均按实际记账。

工程检查400通过（3.78秒），boundary/Ruff/mypy/build通过。新增11项真实Host/mock输入
回归检查原文query仅一次、两臂一致、G/默认不触发、取得时撤权、发送前撤权、未知资格
阻断及工具失败原样呈现。Product源码未改，不产生新迁移。

本例说明：在这个已打开开发条件下，Host确定性激活现有回查后取得正确续做证据；不证明
自主查证普遍成立，也不证明任何查询/家族均有效。后续必须在冻结后的新任务验证来源
获取、首次判断、表示/结构和成本，不能把本例修复升级为留出确认。Goal保持IN_PROGRESS。
