---
status: ACTIVE
scope: MiLAi-Lab
reference_commit: 024fa698b97925dba295c3bd674f820f39559f42
---

# 长程总计划执行 Goal

完整执行[长程总规划](MILAI_LONG_HORIZON_MASTER_DEVELOPMENT_PLAN_20260926.md)，不将总目标缩成v20或某个易通过的实例。各阶段分别保留Goal、freeze和results；阶段通过不等于总Goal完成。研究结论依据实际证据选择GO/PIVOT/KILL，失败先定位问题、比较假设并尝试最小通用修复。

沿用一名Sol xhigh负责源码/config/CI及必要窄测试；Root负责方案、fixture/评分、冻结、所有真实模型与embedding调用（并发1）、连续费用和报告；Luna high负责已授权的Git提交/推送。新增下载如有必要由Luna high执行。默认vLLM设置不变；主开发不换模型或参数寻找最好结果。后续独立sensitivity遵循方法先冻结和matched reference，任何部署变更仍须明确记录依据。

避免防御性平台扩展、通用大审计和重复测试。保留必要身份绑定、实际效果/费用记录与checkpoint边界；每轮只验证真实受影响行为。当前候选先在现有projection模块小幅扩展，机制成立前不为命名重构。

## 全程工作清单

| 阶段 | 交付与完成证据 | 当前状态 |
| --- | --- | --- |
| P0 | 024fa69下A1/A2/A3源码、结果、账本、实际请求证据引用封存 | 完成：[reference](../data/manifests/milai-ser-v20-reference.json) |
| P1 | request-level assistant-output lineage，实际生成request与证据版本可恢复 | 完成，mock重启及实际request证据核对 |
| P2 | A4：A3加ordinary assistant派生文本失效，request-copy only，工具调用历史保留 | 完成，29条受影响窄测通过 |
| P3 | 原changed/retained/irrelevant真实运行；失败按§6/11/32/37继续最小诊断 | 3/3通过，见[P3结果](MILAI_SER_V20_P3_RESULTS_20260927.md) |
| P4 | categorical、boolean、deleted、multi-revision、assistant-only stale非温度控制 | 5/5机制与最终动作通过，[中间表述缺陷保留](MILAI_SER_V20_P4_RESULTS_20260927.md) |
| P5 | correctness成立后可调rank-bounded refresh及必要对照 | 实现/构建完成；保留R1严格2/6，[R2通用目标合同修正4/4](MILAI_SER_V21_P5_R2_RESULTS_20260927.md)；低排名get3→0而tokens略增 |
| P6 | §7全部类型的参数化generalized suite，rubric不进入runtime | 完成最小authority协议修复；最终同源十三例13/13，见[最终结果](MILAI_SER_V21_FINAL_RESULTS_20260927.md)；旧冲突失败不改判 |
| P7 | 已暴露12-case和MERIT arc0回归，保留原失败/费用与matched基线 | 进行中：[R2](MILAI_SER_V22_P7_R2_RESULTS_20260927.md)隔离真实生效，native B1 4/5、A5 3/5；下一步独立修空证据authority开销；R1原十二例和失败全保留 |
| P8 | 方法收敛与formal freeze，逐项满足§25条件 | 待证明 |
| P9 | 运行前选择冻结的unseen matched evaluation，B1/lite/full输入与scorer一致 | 待前置条件 |
| P10 | external baselines、至少两模型族、历史/密度/版本比例鲁棒性及参数边界 | 待方法稳定 |
| P11 | Formation与Post-Action Reconciliation独立Goal/机制/评估，不能混同SER收益 | 待独立研究 |
| P12 | 论文级质量—成本Pareto、错误边界、真实Agent脚本工作负载和复现交付 | 待汇总 |

全程还需覆盖§20–24的多对象/多版本/current冲突、short/medium/long历史及checkpoint边界；§28–30全部指标和完整成本；§43跨session、CRUD、restart、partial failure、无关交错、多用户scope的非benchmark工作负载。Product当前不改；迁移须满足§44。State–Attention、action grounding、Current Evidence Capsule、Jev均按原计划的证据条件决定是否启动，不将“可选”解释为必须提前实现，也不将尚未满足的主阶段冒充完成。

## 反思与进入下一阶段

每个失败结果包含Observed failure、Expected mechanism、Actual causal chain、First broken link、至少两个替代假设、通用修复候选、confounds、最小下一实验和Continue/Pivot/Kill理由。每阶段同时回答§32十项Reflection。

温度一例成功不允许进入formal。当前版本进入请求不等于语义权威或实际被采用；snapshot风险不等于逐词因果。原始失败轨迹不能用后续最好轨迹替换。未见样本一旦参与方法修复即转development。

P6最终source mapping为`7ee904cba80c0facf0f513fe7607b15ea4fa5a61fc1a0553c1ef4e85144411e9`，使用独立P6R2锁。新增authority为模型可见协议干预，每生成额外39tokens；十三例66生成/67293tokens/929embeddingtokens/18exact reads。SER连续账本累计202生成/195740tokens/2837embeddingtokens/75exact reads，unknown/truncation/Judge均0。P5四次目标缩写失败、P6 R1冲突失败、P4中间虚称search都保留。没有整体成本下降或unseen收益结论。v20延后包装项已由P5一次成功构建闭合；P6R2新锁的打包随P7新入口统一完成，不重复旧构建。

总体完成要求以原1422行计划逐项核对：实现、条件判定、分阶段运行、成本、最终研究结论/复现、Luna发布和远端核对均有当前证据；本表的状态不能代替证据。

P7 R2后连续SER为360生成/332460tokens/3902embeddingtokens/75get；0未知/截断/Judge。方法未收敛，master仍ACTIVE；先做独立条件authority修复，然后按§25逐项冻结，继续P9–P12。
