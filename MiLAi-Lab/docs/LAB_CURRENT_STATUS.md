# MiLAi Lab 当前状态

更新日期：2026-10-01。此页提供当前导航；实际用户授权和 Goal 状态优先于历史文件中的 ACTIVE。

| 范围 | 状态 | 依据 |
|---|---|---|
| v13.2 证据关联、增量维护与有界交付 | **ACTIVE**，GitHub草稿PR #79发布后继续；R4全部24/48完成，Root20通过/4失败、22/24未通过；同源码性能完成560/840，10000事件仍在运行；D4–D5未完成，设计资料5篇论文/5项目参考持续归档 | [R4完整结果](../data/manifests/v13-2-e0-r4-results.json)、[阶段性能](V13_2_DERIVED_INDEX_SCALE.md)、[执行记录](V13_2_EXECUTION.md)、[完整验收映射](../data/manifests/v13-2-requirements.json) |
| v13.1 可用性优先开发与实验 | **ACTIVE**，正常门槛22/24；等额配置开发48题对完成，生命周期45/60条尝试、30条完成消息；文稿实跑未开始，完整P0–P8未完成 | [当前实验总结](V13_1_EXPERIMENT_STATUS_20260930.md)；[执行记录](V13_1_EXECUTION.md)；[要求清单](../data/manifests/v13-1-requirements.json) |
| v12 代码组织与 GitHub 发布 | 十五项工程验收完成，PR #76 已合并 | [执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)；[AGENTS](../AGENTS.md) |
| repair v10 实验 Goal | **paused**，未完成 | [总体报告](MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md) |
| R1 标签修复 | 局部输出证据 | [L1](MILAI_REPAIR_V10_R1_L1_RESULTS_20260929.md)、[L2](MILAI_REPAIR_V10_R1_L2_RESULTS_20260929.md) |
| R2 执行保护/恢复 | 工程已实现；真实验证失败且未完成 | [暂停详报](MILAI_REPAIR_V10_R2_PAUSE_RESULTS_20260929.md) |
| R3 形成适用性 | 全 20 题离线审查完成；候选未运行 | [审查清单](../data/manifests/repair-v10-failure-audit.json) |
| R4/R5 写入、身份、时间、格式合同 | 已诊断；效果修复未验证 | [合同审查](MILAI_REPAIR_V10_R4_R5_CONTRACT_AUDIT_20260929.md) |
| R6 预算适配 / R7 独立确认 / 第二模型家族 | NOT_RUN | [要求状态](../data/manifests/repair-v10-pause-summary-20260929.json) |
| Product | **NO_GO** | 结构重构不等于产品验收 |

## 仓库整合

#70–#74 已按依赖顺序合入 main，原提交与冻结 SHA 保留；旧 #51 的改动已被后续提交吸收，
已按 superseded 关闭并保留分支。代码链整合提交为 `8781ad7`，对应 #74 最终 head `97efe0c`。
后者的完整 Fast CI 已通过；Full composition 按规则 skipped，未计作通过。
详细合并 SHA、兼容修复与代码入口见[合并记录](GITHUB_MERGE_AND_STRUCTURE_20260929.md)。
本次合并和导航整理不恢复实验，以下研究限制保持。

v12 从 `cca2fd9` 启动，S0–S7 与一项 CLI 类型修复共九个提交保留于
[PR #76](https://github.com/minguselandy/MiLAi/pull/76)，已合并为 `48ad5439666d5398dff588b052dd80bd04e4ba4b`。
实现 head `a944742ce786ac693c08ac69c4377f82a39afd09` 的 [Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36597268333) 全部受影响检查通过。
[代码结构总体报告](CODE_ARCHITECTURE_V12_RESULTS.md)记录归属、兼容限制、各阶段证据和首轮 CI 失败。
本次文档归档不修改已验收实现，也不恢复研究实验。

## 当前已知限制

R1 L2 两条件均为 20/20 episode，标签复述由 178 降为 0，但两组各有四次附带工单写入。
未证明开放任务的行动可靠性、稳定 unseen 收益或记忆压缩收益；默认仍为 legacy。

R2 仅运行 2/13 次进程、2/12 条公开消息，未完成任何完整恢复案例。
第一条因单复数 key 不一致被阻止；第二条从空记忆检索跳到虚构业务 ID，实际 CREATE 后又
UPDATE 同一记忆记录。业务 world 没有效果，错误正文却真实持久化。当前架构整理保留这一失败，
不放宽授权、不补写正确答案、不继续剩余运行。

## 实验成本与资产

截至暂停，连续累计 6,145 次 generation、11,407,086 generation tokens、416,930 embedding tokens。
v10 新增 153 次 generation、485,745 generation tokens、128 embedding tokens，Judge 为 0。
这些是实验费用，不是开发代理消耗；源码整理与离线检查不改账本。

权威账本为原 checkout 的 `artifacts/ser-v20/budget.json`；SHA256：
`7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`。
既有服务、私密 Store、错误记录、原始 checkpoint、历史锁和草稿保留。
原 repair-v10 工作树中的九个 R2/R3 草稿不复制为正式输入。

## 开发与复现导航

当前结构见[架构文档](LAB_ARCHITECTURE.md)与[项目地图](PROJECT_MAP.md)。
当前实验身份、暂停边界和复核方法见[总体报告](MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md)。
代码整理仅改变实现归属和导航；历史方法按其固定提交复现，既有 PR 不自动合并。

本页替换了长期累积的旧“当前状态”叙述，原文保留在
[固定 Git 快照](https://github.com/minguselandy/MiLAi/blob/091dcbd48dc1800e5b8cc7f0ee3066dc00a76311/MiLAi-Lab/docs/LAB_CURRENT_STATUS.md)。
[结果索引](RESULTS_INDEX.md)和各历史报告继续保留原结论；它们不授权恢复已暂停的实验。

当前v13.1连续账本累计6435generation/11880568generation tokens/420830embedding tokens，unknown0；
本轮外部微型新增48generation/88014tokens/3900embedding，首次Mem0 setup失败与两个回执消费
未通过都保留。此状态覆盖上文v10暂停时的历史费用快照，不恢复其历史实验。

固定material公共合同诊断4generation/4496tokens：两臂业务状态消费改善，但Mem0额外虚构
来源引文，仍失败。原micro5/6结论保留；[P2实际16消息](V13_1_P2_TYPED_RECEIPTS.md)完成8条显式字段形成；后续两臂各2/4符合预定说明，历史未检索送达，Ref另有2条虚构绝对scope。完整P2仍PARTIAL，无全段prose验证承诺。

P2历史送达提示诊断4+2腿仍无memory query，原失败/unknown保留，Attention不准入。新增合计12generation/21439tokens；最新连续6447generation/11902007tokens/420830embedding，unknown0。[直接证据](V13_1_P2_TYPED_RECEIPTS.md)。

[P4已曝光开发2×2](V13_1_P4_TYPE_SCOPE.md)首轮因素混淆保留，R2机械分离成立但类型独立收益未证明。Flat/Type-only/Flat+Scope/Type+Scope task分别2/2/3/2（各4），后者另1UNKNOWN；更广来源归属错误单列。最新连续6511generation/12004306tokens/420830embedding，unknown0。

2026-09-30本次发布快照：原连续账本7461次generation／15742294 generation tokens／538303 embedding tokens，unknown0；v13.1新增1316次／4335208生成tokens／121373嵌入tokens，包含48次同族诊断Judge。上文计数均为历史阶段快照。
[当前总结](V13_1_EXPERIMENT_STATUS_20260930.md)与[机器快照](../data/manifests/v13-1-experiment-status-20260930.json)记录实际分母、失败、成本、来源／服务缺口和未执行项。Luna仅整理总结，不构成独立Judge或第二实验模型家族；完整目标仍ACTIVE，Product仍NO_GO。
