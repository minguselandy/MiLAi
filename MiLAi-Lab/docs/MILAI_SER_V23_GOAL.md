---
status: COMPLETE_WITH_LIFECYCLE_PIVOT
scope: RESEARCH_PROTOTYPE
parent: MILAI_LONG_HORIZON_EXECUTION_GOAL.md
reference_commit: 7f26a9b5f3ff3b5ba54f7c2a0b3dacf3d4d03f90
---

# v23：小规模未见三臂比较

执行结果见[完整报告](MILAI_SER_V23_RESULTS_20260927.md)：B1 6/10、A3/A4各7/10，全部0exact refresh/derived demotion，不成立SER自然收益结论。六条预注册轨迹及费用保留，连续SER568生成/530611tokens/5057embeddingtokens/75get。决定优先独立Formation/Reconciliation；第二模型族和P10/P12未完成，master继续。下文为调用前原方案，其原字节可从`f096e40`恢复。

[P8方法冻结](MILAI_SER_V22_P8_METHOD_FREEZE.md)已经发布并核对remote。本阶段执行总计划P9；不把既有机制控制、原arc0或十二例回归当成未见收益。当前模型/工具/协议与方法参数全部固定，v23只接通被冻结的原始selection。

## 在任务生成前预注册

使用同一官方MERIT commit `293933d96b1d1849e1f20d1bb324def5de9ed33f`，原`generate_suite`；每个base_seed各生成一个hard arc，episodes_per_arc=5，dep_ratio=0.5。选择base_seed=3、4：已暴露0/1/2后的两个顺序种子，当前未生成/未打开，不按题内容或分数筛选。源代码冻结后才生成这两份任务及原world，字节SHA、原分母和公开消息数随后冻结。全部原消息和次序保留，不改原合并任务评分规则。

每个seed依次运行`b1_control`、`a3_exact_refresh`、`a4_selective_rebase`，seed升序，共六条新轨迹。每臂独立空namespace和同一原world；Host跨episode重置，Store/world保留，同episode多消息历史保留。recipe/transport仍v21；两个SER臂同stage v21条件authority，A3只quarantine+exact refresh，A4另做derived rebase，两者无rank截断。A3已有lineage观察开销仍计费，不临时优化。A5总体优势未证，留开发消融而不加入本轮。

唯一新实现为通用`load_frozen_arc`、共用原loop的新入口和薄CLI；旧`load_exposed_arc`仍精确限定seed0。源与包身份、新入口、三臂接线在必要零模型验证后冻结；不复制业务loop/scorer，不改算法或提示，不读未来任务内容。Root生成并冻结每seed selection/arc/world后才prepare和真实调用。

## 统一运行及判定

现有Qwen3.6-35B-A3B-FP8、temperature0、thinking=false、max_tokens4096；每公开消息12生成，embedding仍bge-m3/1024，vLLM设置不变。并发1，原SER账本起点415生成/373013tokens/4370embeddingtokens/75exact get，绝不清零。R2局部容量失败策略所有臂一致，已发生业务不回滚；Host失败/skipped和原世界checker分别报告。服务/Store等错误先定位，不能无限重试或重置容量。

保留原native/dependent分母、`not pre_satisfied and checker(after_world)`、原memory tracer。补充核对真实动作参数、早期信息形成、自然revision、实际Provider CURRENT/stale交付、derived demotion、动作后记忆状态和成本。checkpoint内搜索命中不冒充实际Provider送达或因果采用；无自然stale时相关分母undefined。只做完整语义评审与原native checker，不引入Judge模型。

主报告逐seed及汇总三臂，不用单次最好run、混合source或换题。两arc只支持小样本结论，不估计总体可靠性。效果出来后不改prompt；若发现通用实现bug需最小修复和新源锁，旧结果费用保留，受用于修复的样本改记development。

若SER有明确自然适应链且质量/成本值得进一步验证，按P10条件进入robustness；若baseline不劣、方法不激活或复杂度无支持，按总计划作PIVOT/KILL判断，转入独立Formation/Reconciliation研究。P10第二模型与大范围敏感性须先有主效果证据，不为了完成列表提前扩测。P11和P12非benchmark脚本、质量成本、边界与复现仍须完成。

## 完成清单

- [x] selection规则与三臂预注册，未见任务生成前完成。
- [x] 单loop薄接线、窄验证、源码锁和一次必要package。
- [x] 两arc原字节冻结、六条预定运行，全部容量/语义失败及费用保留。
- [x] 原scorer/实际wire/语义/成本、Failure Review与十项Reflection。
- [x] 依据结果PIVOT主开发到生命周期；调用前冻结已发布核对。
- [ ] Luna发布本轮结果并核对remote；master继续。
