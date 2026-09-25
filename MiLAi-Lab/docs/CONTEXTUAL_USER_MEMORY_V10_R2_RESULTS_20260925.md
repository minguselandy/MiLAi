# v10 R2：同题修复后比较与研究结项

**状态：`COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`。** B–D 工程和 §8 要求的真实采用→新观察→Host 重核→后续使用链已有证据；在这一个已暴露原生 arc 中，强工作笔记的任务分数更高、费用更低。因此 ordinary 仍为默认，单决策依据不升级为默认方法，也不宣称一般可靠性或因果收益。[R1 原失败报告](CONTEXTUAL_USER_MEMORY_V10_RESULTS_20260925.md)与费用保持原样；R2 是新源码身份下的第二次完整尝试。

## 范围与身份

两臂分别从原始空记忆及业务世界开始，按原到达顺序执行 MERIT `arc0-000` 全部 5 个 episode、7 条公开消息及原生工具/checker；原 session 边界不变。单控制器并发 1、源码／配置运行前后相同。47 文件映射 SHA-256 为 `6528ff9c69a567d40afb096e7ecb1c4e81aeafb3bee0c23b4dba20c57f58e9f4`，每臂配置 SHA、原始 arc/world SHA 和独立 freeze 见[紧凑结果清单](../data/manifests/contextual-memory-v10-r2-results.json)。这是先前已暴露的一个 arc，不是未见集或多个独立样本。两臂有相同合法任务、记忆 CRUD、工具、上下文／输出容量；notes 在正常响应中自由维护判断、引用、缺口并可自主查询，basis 在同次响应中维护结构依据。全部响应计费。

| 实际结果 | 强笔记 notes | 决策依据 basis |
| --- | ---: | ---: |
| 原生任务通过 | 5/5 | 4/5 |
| 依赖任务通过、实际利用记忆 | 2/2 | 2/2 |
| Host complete / 全部轮次 | 7/7 | 7/7 |
| 维护待办未清的 episode | 0 | 0 |
| 实际笔记变更／决策 delta 接受 | 24 | 23 |
| 自动版本重核通知 | 不适用 | 0 |
| 生成请求 | 26 | 45 |
| 输入／输出／合计 generation tokens | 203165／31667／234832 | 407174／121462／528636 |
| embedding 请求／tokens | 12／2166 | 11／2027 |
| 截断生成 | 1 | 18 |
| 写入／finish 拒绝 | 1／0 | 1／0 |

basis 较 notes 多用 293804 generation tokens（约 125.11%），原生少通过 1 个 episode。basis 截断的 18 次计 234437 tokens，已包含在其总费内；截断输出未执行其部分动作。两臂各有一次可见正文不足导致的 `memory_save` 合同拒绝，后续是否成功以真实提交回执计，拒绝不算持久写入。无 provider HTTP 失败、unknown usage 或 Judge 请求。此比较只有各臂一条完整轨迹，结果不识别纯五字段表示、提示、通知或缺口检索的独立效应。

## 任务动作、维护与机制链

basis episode 2（从 0 起）的已交付用户确认来源 `m10`（`86f160e0d741454c/source:7a0e195c8a71662fbaab11ba`，`[0,137]`）在第 20 次生成被准确采用，随后执行真实退款；成功结果成为新观察 `m11`（`86f160e0d741454c/source:88b69bfc8d81c2dc3864831a`，`[0,250]`）。同一 `decision_id` 的第 23 次生成将采用改为 `m11`、清除待确认缺口并读取旧待办卡；第 24 次生成后，`memory_save REVISE` 把该卡 pending→processed，得到 `COMMITTED` 回执。期间有一次正文未读的写拒绝和一次输出截断，链条并非无失败的连续三步。这是同一 Host 正常动作中的**新观察语义重核和后续使用**，不是自动版本变化通知，也不表示程序认证了材料的语义支持。终态离线检查得到 23 次接受的 delta、均含非空采用、自动通知 0；全部实际采用指向 source，而非历史解释版本。`critical_gap` 有时被写成字面字符串 `"null"`／`"none"`，与真正空缺口不能混同；实际 `critical_gap` 焦点查询为 0，未认定焦点查询的收益。

basis episode 4 与 notes 均真实退款 6595 cents，并将原待办卡修订为 processed；basis 使用 `source_delta.add` 并得到 `COMMITTED`。两臂 Host 均完成，不能以此代替原生任务评分。basis episode 3 未执行退款；虽发送了客户消息并声称已提交审批，轨迹中没有实际审批工具或提交回执，原生 checker 判失败。notes 该 episode 通过。这个差异是业务行为，不应由完成回执或发信成功掩盖。

## Goal §8 的判定边界

| 条件 | R2 证据与判定 |
| --- | --- |
| 工程与真实可操作 | B–D 已实现；42 项 Host／decision 窄测、终结回执后 8 项窄测及 Ruff 已通过；R2 有 23 个同次生成并接受的真实 delta，不是固定额外 State 调用。满足受限工程门槛。 |
| 机制可达 | episode 2 的 `m10`→退款 `m11`→同 decision 重申采用／清缺口→读旧卡→REVISE `COMMITTED` 可逐项核对；保留期间拒绝与截断。满足一条新观察链；自动旧版本通知仍无真实触发证据。 |
| 任务行为与方法收益 | 原生分数、业务回执、持久维护与 Host 状态已分列。notes 5/5 对 basis 4/5，basis 费用更高；受限比较为负面／不确定效果，不能证明改善。 |
| 范围与交接 | 原题、原 checker、7 条消息、原 session 与连续账本保留；R1 和所有截断／拒绝也保留。无 Product 改动、全套或新候选扩展。身份、费用及原始证据可追溯。 |

E2 gap-focus 消融 **NOT_RUN**：实际 `critical_gap` 焦点查询为 0，缺适用对照前态。E3 自动通知消融 **NOT_RUN**：全部实际采用是 source，没有真实版本通知；R2 的实际链是新观察后的 Host 重核，不能拿它替代版本通知收益。E4 **NOT_RUN**：原生任务没有同一决策跨原始 session 持续复用的自然窗口。StateMemBench **NOT_RUN**：未取得可核验的官方数据、许可及 scorer。文档四轮未为加通过数重复运行；全量套件／benchmark 和 Product 迁移不在范围内。上述未运行项不是零分，也不是能力否定。

## 连续费用和复核入口

R1 保留 51 次／452656 generation tokens／3955 embedding tokens；R2 新增 71 次／763468 generation tokens／4193 embedding tokens。v10 终态账本共 **122 次生成／1216124 generation tokens／8148 embedding tokens**，unknown=0、Judge=0。旧 v9 账本的 SHA 与 119／966332／4358 保持独立，未清零或并入 v10。R2 两臂完整请求、原生结果、业务世界、checkpoint、trace 与 accounting 在 ignored `artifacts/contextual-user-memory/v10-e1-attempt-2/`；[紧凑清单](../data/manifests/contextual-memory-v10-r2-results.json)记录关键路径及 SHA。离线 `inspect_decisions.py` 的终态输出为 23 accepted、23 nonempty adoptions、0 notice；其统计不替代上述原生／业务语义核对。

两臂摄入均无额外 generation 请求，Judge 为 0；实际 embedding cache hits 均为 0。按响应主要动作划分的 generation tokens 见紧凑清单 `generation_by_primary_action`：basis 的 18 次失败／截断共 234437 tokens，notes 的 1 次为 14485。状态或笔记与动作在同次生成，共享推理和重复输入不能精确拆为独立的边际 State 费用；这些组只是描述性成本分区。

交接边界：Lab `HostResult` 新增最终 `active_decision`／`work_note` 快照，不把临时判断冒充业务成功。Product API、Schema、权限和 Canonical 状态未改；未搬包边界，因此未扩展边界门禁、构建或全量测试。回退基线提交为 `001a6eebed52caecfc1c5c52fa830c57b837fb4a`，R1 与 R2 的真实账本及源码身份分别保留。
