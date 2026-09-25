# v11 稀疏 Basis 与 Attention：固定小比较

状态：`COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`。固定两个原生实例的六臂比较及问题驱动的 R3 工程修复完成。A2 两个实例都为 5/5，但自动 gap 检索和版本通知均未发生；完整的第二个实例中，Notes 同为 5/5 且费用更低。未建立总体质量—成本或 Attention 收益，ordinary 仍为默认。

## 实验与源码身份

[Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v11.0_20260925.md)及[详细设计](MILA_CONTEXTUAL_USER_MEMORY_V11_SPARSE_BASIS_DESIGN_20260925.md)限定两个原生完整实例、三臂、串行调用。A0 为自由工作笔记；A1 为 Sparse Basis、自动版本反馈；A2 仅在 A1 上开启普通无 query 搜索的自动 gap 解析。A1 仍可显式写 query，也可显式请求 critical_gap。三臂使用同一维护合同、工具、模型与容量，Basis 两臂共享 schema 和提示。

初次实现 R1 的 48 文件映射为 `3cefb731f5379b2ea7ab1d5ce1725ca1a226c74228ab3f8709190a5257d913e9`。旧 arc 的维护终结失败后，共享说明澄清“本轮记忆维护”与“未来业务等待”，形成 R2 映射 `2a95dcd0fde0e90a4eff053b5875d0f6d07a3ec61961fd158201c312102d1cf4`，源码已保存在 Git `22e0f22d99a777e8fdb0c56edc222ee522402794`。本次 F 比较全部使用 R2；旧失败和恢复不被替换。

F 过程中确认两处 Host 缓存过度失效，后续 R3 修复先使用独立工作区，不在六臂中途改源码。全部 F 终结并汇总后合入，又修复错误回执投影，最终映射为 `666344907d0ef59f171431ebc7e572b92bf68fae2378f82fc32dc8df4fff7c12`。R3 的确定性检查与 R2 的真实模型结果分开；这次比较不是 R3 的未见验证，没有补选新题或重跑到成功。

[选择规则](../data/manifests/contextual-memory-v11-selection-policy.json)先于新题生成发布。按两个最小未暴露正 base_seed 得到 `arc1-000`（seed 1，5 集／6 条公开消息）和 `arc2-000`（seed 2，5 集／7 条消息），各含两集 dependent 任务。MERIT 固定官方提交 `293933d96b1d1849e1f20d1bb324def5de9ed33f`；原生消息、世界与 checker 原样保留。两个实例复用同一任务生成器模板，不能代表新任务类型或广泛泛化。

运行顺序事先固定为 arc1 的 A0→A1→A2、arc2 的 A2→A1→A0；每个 arm×arc 独立世界、空记忆及新 embedding cache。Qwen3.6-35B-A3B-FP8 经 vLLM，thinking 开、temperature 0、4096 输出、65536 上下文、每条公开消息最多 12 次生成；bge-m3 embedding 1024 维、批量 32。权重、tokenizer、配置与准备身份见[选择回执](../data/manifests/contextual-memory-v11-f-selection.json)及[六臂准备清单](../data/manifests/contextual-memory-v11-f-prepared.json)。本轮没有第二模型、额外语义 Judge、全量测试或扩展 benchmark。

## 如何阅读结果

原生业务 checker、Host 终结、记忆维护分别列出。中止的整条 arc 保留 `UNSCORED_INCOMPLETE`，不能用已通过前缀替代完整分母。补充的保存世界检查把未改的原生 checker 应用于实际 before／after 世界，包括中止快照；这可确认已发生的业务效果，但不把 Host 或维护改判为完成。未运行的 episode 仍未评分。

请求占用是请求构造时存在 Basis 的次数／全部生成，包含截断；动作占用是 sidecar 实际接受之后有 Basis 的执行步骤／全部实际执行步骤。激活、实质修订、clear、null、同值 set、已空槽上的 clear 分开。生命周期同时给出占用步骤和创建至结束的请求跨度；结束窗口含 clear、null-gap 解决和原生 session 重置，不把重置视为 Host 主动清理。

[原生变化机会表](../data/manifests/contextual-memory-v11-native-opportunities.json)独立于 Host 轨迹标注 13 条消息：8 次明确改变同一事项的既有表述，5 次为首次或不同事项。8 次变化均跨原生 episode，不能直接作为同一个未解决 Basis 的版本重核机会。原题没有 Basis-needed 或自动版本通知必要性的标签，二者 13/13 为 unknown；不报告 precision／recall。消息变化、自动版本通知、新观察投影和 Host 接受的声明分别计数，声明本身不证明语义重核有价值。

gap utility 逐级检查：存在可用 gap → Host 请求搜索 → 实际有效 gap 查询 → 新相关材料 → 后续采用。初始普通记忆检索另属会话初始化，不混成 Host 主动 memory_search。返回错误的搜索仅算调用尝试，不能把空错误投影解释为成功零命中。R2 的 `retrieval_executed` 字段仅表示非缓存 dispatch，最终分析必须结合真实工具回执；R3 将明确区分 `dispatch_attempted`、`search_ok`、`operation_completion` 与本次成功检索。

所有生成失败、拒绝和截断保留在费用中。投影、固定说明、历史 sidecar 与 sidecar 输出使用冻结 tokenizer 作本地分段估算；State 说明是完整固定合同的子集，分段不保证可加。共享 reasoning、schema 的独立计费与反事实额外请求不能精确归因给 State。provider usage 是唯一总账，embedding 单列，不把不同模型 tokens 混成精确货币。

## 旧 arc 接线诊断

首次 R1 完整尝试在 episode 3 的维护 pending 中止；前 3 集原生通过，5 个 Host 回合完成，最后一集未运行。33 次生成、344195 generation tokens、1914 embedding tokens，11 次截断均计入。一次实际状态上的 finish 恢复增加 1 次生成、8669 tokens，仍 pending，没有重做业务。

R2 的原始干净后缀从 episode 2 结束的持久记忆与业务世界接续 episode 3、4，两个 Host／维护均终结；原生分别失败／通过。episode 3 未实际提交审批，不能把回答中的审批声明当作业务回执。后缀新增 20 次生成、226865 generation tokens、36 embedding tokens；它复用诊断 embedding cache，且前缀／后缀源码不同，不能作为单一源码五集成功或冷启动费用。

E 合计 54 次生成、579729 generation tokens、1950 embedding tokens，unknown=0、Judge=0。完整失败、定向恢复、后缀的身份与制品 hash 分别见[首次尝试](../data/manifests/contextual-memory-v11-e-first-attempt.json)、[恢复](../data/manifests/contextual-memory-v11-e-recovery.json)、[后缀](../data/manifests/contextual-memory-v11-e-suffix.json)。

## F：原生结果与终结状态

完整身份、制品 hash、每集结果、真实动作、逐请求位置及机会配对见[结果清单](../data/manifests/contextual-memory-v11-f-results.json)。

| 实例／臂 | 整条 arc 原生评分 | dependent | Host 完成／计划消息 | 保存世界 checker |
| --- | --- | --- | --- | --- |
| arc1-000 A0 | 中止，整条未评分 | 整条未评分 | 5/6 | 5/5 个已到达边界（含中止快照） |
| arc1-000 A1 | 中止，整条未评分 | 整条未评分 | 4/6 | 4/4 个已到达边界（含中止快照） |
| arc1-000 A2 | 5/5 | 2/2 | 6/6 | 5/5 个已到达边界 |
| arc2-000 A0 | 5/5 | 2/2 | 7/7 | 5/5 个已到达边界 |
| arc2-000 A1 | 4/5 | 1/2 | 7/7 | 4/5 个已到达边界 |
| arc2-000 A2 | 5/5 | 2/2 | 7/7 | 5/5 个已到达边界 |

arc1 A0 的最后一次退款已经成功，随后 3 次记忆写入拒绝与 5 次截断耗尽本轮容量，未给出维护终结。A1 在 episode 3 已发送新金额确认，但 2 次写入拒绝与 7 次截断后仍未完成维护，episode 4 未运行。两条中止轨迹不能通过补充世界检查改成完整成功。

arc2 A1 的 Host／维护全部 complete，却只有 4/5 原生通过：episode 2 对第一个订单确认了 **8654 cents**，三个 REVISE 提案均被拒绝，Host 随后声明本轮 processed。下一集从旧记忆取出 **6720 cents** 并实际退款 6720；工具执行成功，但金额不符合原生 checker。源码还确认，写入投影保留了失败状态，却丢掉具体失败原因；R3 修复交付错误码，不回写这次失败，也不声称重跑后一定正确。

A2 两个实例均为 5/5，但 arc1 episode 2 退款后没有提交新的完成状态记忆便声明 processed。原生业务成功仍不能证明所有长期记忆维护都正确。最终报告不把 complete 或结构化合法性作为语义可靠性的替代。

两个实例的 A1／A2 首个 provider 请求在规范化后完全相同，实际 action 不同；两对请求 hash 已保存在结果清单。temperature 0 没有令本次部署的重复运行逐字一致。自动 gap 路由实际从未触发，因此不能把分数或截断差异归因给这个分支。

## 稀疏性、转移和生命周期

| 实例／臂 | 请求前占用 | 动作占用 | 激活 | 实质修订（不含创建） | 显式 clear／null-gap 结束 | 请求前 gap 可用 |
| --- | --- | --- | ---: | ---: | --- | ---: |
| arc1-000 A0 | 0/30 | 0/21 | 0 | 0 | 0/0 | 0 |
| arc1-000 A1 | 14/36 | 6/17 | 4 | 1 | 3/0 | 14 |
| arc1-000 A2 | 4/24 | 4/20 | 2 | 2 | 0/2 | 4 |
| arc2-000 A0 | 0/27 | 0/24 | 0 | 0 | 0/0 | 0 |
| arc2-000 A1 | 2/35 | 2/27 | 2 | 0 | 0/2 | 2 |
| arc2-000 A2 | 8/32 | 5/26 | 3 | 2 | 2/1 | 8 |

A1 合计请求占用 16/71、动作占用 8/44；A2 为 12/56、9/46。这些是观察值，未设通过阈值。F 中没有同值非空-gap set 的 no-op，也没有 REVIEW_ACKNOWLEDGED。记录的 41 次 NO_STATE_CHANGE 全部是已空槽上的 clear 或 null-gap set，不能宣传为 41 次避免了有意义的 State 重写。旧 arc E 首次尝试有 1 次 review acknowledgement，仍仅属于已暴露接线证据。

| 实例／臂 | 每个生命周期的请求前占用步数 | 动作占用步数 | 创建至结束的请求跨度（含两端） | 实质修改／占用动作，即 churn |
| --- | --- | --- | --- | --- |
| arc1-000 A1 | 1, 1, 9, 3 | 1, 1, 3, 1 | 2, 2, 10, 4 | 0/1, 0/1, 1/3, 0/1 |
| arc1-000 A2 | 2, 2 | 2, 2 | 3, 3 | 1/2, 1/2 |
| arc2-000 A1 | 1, 1 | 1, 1 | 2, 2 | 0/1, 0/1 |
| arc2-000 A2 | 4, 2, 2 | 1, 2, 2 | 5, 3, 3 | 0/1, 1/2, 1/2 |

arc1 A1 的一个 Basis 在 episode 1 结束时仍保留 `memory_update_for_revised_refund`，随后由原生新 session 重置，非 Host 主动 clear。其余十个生命周期均有明确 clear 或 null-gap 结束。不存在清除后的隐藏监测槽。

| 实例／臂 | 完整可解析 set／clear／null | 不可解析输出 | sidecar 输出分段 tokens |
| --- | --- | ---: | ---: |
| arc1-000 A1 | 5/10/4 | 17 | 693 |
| arc1-000 A2 | 8/3/11 | 2 | 1007 |
| arc2-000 A1 | 10/8/10 | 7 | 1169 |
| arc2-000 A2 | 18/10/0 | 4 | 1765 |

可解析提案包括被拒绝的提案，不能与接受转移混算。arc2 A2 的 28 个可解析响应没有一个 null，虽然请求占用只为 8/32；低占用并不代表重复声明已经解决。实际 gap 还包含 `send_confirmation_message`、`save_pending_refund_memory` 等待办动作，未完全符合“未解决的信息分歧”语义。没有新增语义审核或按目标占用率强制清状态。

## 重核机会与 Attention 实际消费

F 的自动版本通知为 0；实际保留在活跃 Basis 中的采用引用均为 source，另有空采用集，没有活跃 Basis 采用的 MemoryCard 后续变版窗口。13 条原生消息中 A0/A2 实际各收到 13 条、8 次同事项变化；A1 收到 12 条、7 次变化，另一条因 arc1 中止而未到达。不同 episode 的变化仍进入普通记忆流程，不能为了通知覆盖而合并 session。

| 实例／臂 | 新观察投影请求数 | 不同 Basis×观察对 | 之后接受的转移 |
| --- | ---: | ---: | --- |
| arc1-000 A1 | 6 | 4 | CLEARED 3；STATE_CHANGED 1；NO_ACCEPTED_DELTA 2 |
| arc1-000 A2 | 4 | 4 | STATE_CHANGED 2；GAP_RESOLVED 2 |
| arc2-000 A1 | 2 | 2 | GAP_RESOLVED 2 |
| arc2-000 A2 | 4 | 4 | STATE_CHANGED 2；CLEARED 2 |

上述观察主要是订单查询／发消息的业务回执。程序证明它们被呈现，随后 Host 选择了 set、clear 或 null-gap；这不是独立的语义重核正确率。版本通知、同值确认与有效 gap 检索在 F 中仍为 NOT_OBSERVED，窄单测只证明相应路径可执行。

六臂共 **1 次 Host 主动 memory_search**：arc2 A2 显式 query=`address`，显式 query 优先于同次建立的 gap；`known_at=m0` 把材料别名当成时间，回执为 REJECTED/failed，返回 0 份材料。后续 CREATE 采用的是此前已交付的用户消息与 update_address 业务回执。故有效 gap 查询 0、新 gap 相关材料 0、后续采用 gap 材料 0；这次失败调用也不算成功零命中搜索。搜索缓存命中 0，缓存修复的原生节省未被本样本证明。

## 全部成本与截断

| 实例／臂 | 生成请求 | 输入 tokens | 输出 tokens | generation 总量 | embedding tokens | 截断／生成 | 截断请求总 tokens | 写入拒绝 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| arc1-000 A0 | 30 | 242755 | 54757 | 297512 | 1987 | 6/30 | 80039 | 3 |
| arc1-000 A1 | 36 | 294689 | 98603 | 393292 | 1671 | 17/36 | 214556 | 2 |
| arc1-000 A2 | 24 | 193101 | 41598 | 234699 | 2008 | 2/24 | 25758 | 2 |
| arc2-000 A0 | 27 | 216812 | 38769 | 255581 | 2035 | 3/27 | 34294 | 0 |
| arc2-000 A1 | 35 | 290811 | 73436 | 364247 | 2169 | 7/35 | 86820 | 6 |
| arc2-000 A2 | 32 | 271457 | 56580 | 328037 | 2454 | 4/32 | 42776 | 2 |

F 合计 **184 次生成、1509625 输入＋363743 输出＝1873368 generation tokens、12324 embedding tokens**。39 次截断消耗 484243 tokens（约 25.8%），均已计入；所有截断请求均没有部分 dispatch。最长连续截断为 arc1 A1 episode 1 的 7 次，episode 3 另有连续 6 次，最终容量耗尽使下一集未运行。逐请求位置和 streaks 全部在结果清单。HTTP 失败、finish 拒绝、unknown usage、Judge 均为 0。

包含 E 的所有失败、恢复与后缀，v11 连续总账为 **238 次生成、2453097 generation tokens、14274 embedding tokens**，unknown=0、Judge=0。封存 v10 仍为 122／1216124／8148；v9 仍为 119／966332／4358，其账本 SHA 已核对未变。开发代理与工具编排不属于 benchmark provider tokens；未做精确货币估算。

按三臂汇总，A0 为 57 次／553093 generation tokens，A1 为 71 次／757539，A2 为 56 次／562736；但 A0、A1 各有一条中止轨迹，不能忽略完成范围直接比效率。在完整的 arc2，A0 与 A2 都为 5/5，A2 多用约 28.3% generation tokens；A1 为 4/5，多用约 42.5%。arc1 的 A2 更完整且费用更低，但本轮只有两个实例，且未执行任何 gap 查询，无法据此识别 Attention 因果收益。

| 实例／臂 | 当前 Basis 投影 | 固定合同全部 | 其中控制说明 | 历史 sidecar | sidecar 输出 |
| --- | ---: | ---: | ---: | ---: | ---: |
| arc1-000 A0 | 0 | 146674 | 2100 | 1969 | 619 |
| arc1-000 A1 | 2428 | 178095 | 5400 | 4826 | 693 |
| arc1-000 A2 | 901 | 119121 | 3600 | 3149 | 1007 |
| arc2-000 A0 | 0 | 132100 | 1890 | 1441 | 593 |
| arc2-000 A1 | 346 | 174099 | 5250 | 4098 | 1169 |
| arc2-000 A2 | 1146 | 159159 | 4800 | 5713 | 1765 |

A0 的控制说明／sidecar 是 work_note，Basis 臂为 state_delta；“固定合同全部”已经包含该说明子集，不能重复相加。当前投影只是输入的一小部分，不能据此断言 State 总推理负担很低。全部 39 个截断输出没有可执行 JSON，其 sidecar 成本未知，不能计为 null。共享 reasoning 有文本但没有可靠独立 provider token 项，schema 独立开销与额外请求的反事实归因均保持 unknown。

## R3 工程修复与验收范围

最终[修复冻结清单](../data/manifests/contextual-memory-v11-repair-freeze.json)保存 48 份运行源码／配置映射，以及受测的两份源码、三份测试 SHA。相对 F 的 R2，只改变 Host 与 MaterialView：

- Host 共用读缓存不再因无关 Basis focus 变化无条件清空；search 材料身份移除纯确认元数据 `recheck_reasons`。真实 query、材料版本、来源及删除变化继续参与已有失效路径，已交付版本通知仍可确认。
- 检索事件区分 dispatch 尝试、真实回执是否成功、操作终结状态与本次成功检索。失败前是否发生部分内部工作不作推断；缓存命中不算新检索。
- 搜索错误保持 ERROR，不再投为 NO_MATERIALS；读写错误保留可公开的核心错误码，例如 INVALID_KNOWN_AT。非代码异常文本可能包含未交付的内部引用，因此仅返回通用错误码，不泄露原文。

新增缓存测试在旧代码上确实发生两次检索；新错误交付测试在旧代码上得到 NO_MATERIALS，均先失败再通过。最终三个受影响文件共 **59 passed**，两源码的 mypy、两源码及三测试的 Ruff 通过。初始 14 项缓存／Basis 检查包含在这 59 项内，不累计成额外覆盖。已证实真材料变化、有效查询变化仍重检索，拒绝搜索不计成功，版本通知不被隐藏。

下层 `latest_search` 是旧 State coverage 的准确选择绑定，切换焦点后的清理保留；State-only RETRIEVE_ONCE 扩展不在 v11 ordinary/off 路径激活，未借此重写旧 State。R3 没有修改 prompt、请求 schema、checkpoint 格式、ranking 或原生任务；METHOD v16、Basis v2、JSON-action v3、配置 v11 保持兼容，源码 hash 单独识别修复。没有为 R3 再购买模型调用，其语义恢复效果仍未实测。

| Goal 工作包／约束 | 当前完成证据及边界 |
| --- | --- |
| A：旧证据、事实与推断 | [固定 R2 离线诊断](../data/manifests/contextual-memory-v11-baseline-diagnosis.json)；旧失败、声明与真实业务动作分开，v10/v9 账本 hash 未变 |
| B：稀疏合同、引用、no-op／ack、恢复 | [初次开发清单](../data/manifests/contextual-memory-v11-development.json)的 94 项受影响窄测覆盖 nullable／哨兵、准确采用集合、已呈现／未呈现通知、重核游标、持久恢复及不重执行业务；R3 再补真实缓存回归 |
| C：查询、缓存、紧凑投影 | 同一 query resolver 用于 preflight、dispatch 与 cache；初始 active gap、explicit 优先、deferred／clear、新材料与新 task query 已在窄测覆盖；15 个部署 decoder 探针与三份固定投影比较为零模型工程证据；R3 保留错误状态／原因 |
| D：准备、身份、成本 | 参数化原生 selection；六臂准备身份、工具校验、原始 arc/world、checker 与配置 hash 保留；provider 回执与连续账本逐项一致，拒绝／截断不扣除 |
| E：一次旧 arc 与定向诊断 | 首次中止、一次 finish 恢复、原始后缀均保留；没有循环完整旧题至 5/5；后缀不冒充单源码全程成绩 |
| F：固定两个未暴露实例 | 预定 seed、完整原生序列、独立 arm×arc 初态、平衡顺序、单入口并发 1；六臂全部达到终结结果或保留中止，无替换题目；分数、实际业务、维护、机会、生命周期和全部费用已报告 |
| 范围与边界 | Lab-only；无 Product API、Schema、权限或 Canonical 修改，无新跨包依赖；没有迁移、模型训练、第二模型、第四臂、全量测试、扩大 benchmark 或新增语义审核 |

94 项初始窄测、48 项维护说明修复检查、59 项最终修复检查彼此重叠，不能相加宣传独立测试数。请求 schema 在 R3 未变，因此未重复 decoder 检查；包结构和依赖未变，因此没有重复构建或全量边界套件。源码／文档／紧凑清单进入 Git；原始模型输出、业务世界、数据库、缓存和完整数据仍 ignored。F 对应的可回退提交为 `22e0f22d99a777e8fdb0c56edc222ee522402794`，最终 R3 发布由后续 Git 提交及远端 SHA 核对确认。

本轮按 Goal 允许的负面／不确定结论完成有范围的研究。仍未证明自动 Attention、版本通知或总体效率收益；维护误判、错误金额、冗余 sidecar 和高截断率都是实际限制。保留 ordinary 与 Notes 强基线，不扩题、不追加候选，不把工程修复或两个实例成功提升为一般可靠性结论。
