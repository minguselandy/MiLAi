# MiLAi Lab 当前状态

更新日期：2026-09-29。此页提供当前导航；实际用户授权和 Goal 状态优先于历史文件中的 ACTIVE。

| 范围 | 状态 | 依据 |
|---|---|---|
| v12 代码组织与 GitHub 发布 | Goal active，实施中 | [执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)；[AGENTS](../AGENTS.md) |
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

后续 v12 从 `cca2fd9` 启动。S0 文档提交为 `19339bff`，S1 公共合同与请求呈现提交为
`02dfacdc`，S2 通用记忆服务提交为 `379ad45e`，均已通过本地工程检查；
S3 外部集成提交为 `5aa61b8d`，同样通过本地检查。上述提交尚未发布到远端 main；
S4 benchmark 公共执行流程已通过本地检查，待分组提交；S5–S7 尚未完成。
最终发布与受影响 Fast CI 仍待完成，不能使用上一轮 CI 代替本轮验收。

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
