---
status: PAUSED
scope: MiLAi-Lab
reference_commit: 024fa698b97925dba295c3bd674f820f39559f42
---

# 长程总计划执行 Goal

> 最新状态（2026-09-27）：LSA复盘当前E2切片完成后，用户要求暂停，实际thread Goal已paused。
> 总目标仍未完成；旧激活及下一步段落保留历史证据，不能恢复执行。
> [最新总体报告](MILAI_LSA_REVIEW_OVERALL_EXPERIMENT_REPORT_20260927.md)记录完整结果与未完成项。

2026-09-27 新授权：用户要求完整执行
[局部多 State–Attention 规划](MILAI_LOCAL_STATE_ATTENTION_DEVELOPMENT_EXPERIMENT_PLAN_20260927.md)。
当前开发转入[LSA 执行 Goal](MILAI_LOCAL_STATE_ATTENTION_EXECUTION_GOAL.md)，此前暂停对该新范围解除。
下列 SER/P0–P12 表保留历史证据；其未触发的 Attention 限制不阻断新授权方法。
旧模型敏感性 v27 草稿继续保留，不作为部署授权；总目标和第二模型等证据缺口尚未完成。

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
| P7 | 已暴露12-case和MERIT arc0回归，保留原失败/费用与matched基线 | 开发验证完成：[R3](MILAI_SER_V22_P7_R3_RESULTS_20260927.md)诊断7/12，MERIT4/5；固定B1参考8/12、4/5，原失败保留；无端到端收益结论 |
| P8 | 方法收敛与formal freeze，逐项满足§25条件 | [九项判定与方法冻结](MILAI_SER_V22_P8_METHOD_FREEZE.md)完成，允许小规模检验；不等于最终质量GO |
| P9 | 运行前选择冻结的unseen matched evaluation，B1/lite/full输入与scorer一致 | [v23六条已完成](MILAI_SER_V23_RESULTS_20260927.md)：B1 6/10，A3/A4各7/10，0自然refresh/rebase；负面证据保留，PIVOT至生命周期 |
| P10 | external baselines、至少两模型族、历史/密度/版本比例鲁棒性及参数边界 | [v26外部形成对照](MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md)完成：B1 2/4、Mem0 4/4，生成tokens 10.1倍；原四例系统比较。第二模型独立端点仍未获得；广泛扫描条件未触发，P10不标完成 |
| P11 | Formation与Post-Action Reconciliation独立Goal/机制/评估，不能混同SER收益 | [v24独立Goal](MILAI_LIFECYCLE_V24_GOAL.md)负结果完成；F三候选均0/2，R1/R2均2/3且必要更新0/1；[R2](MILAI_LIFECYCLE_V24_RECONCILIATION_R2_RESULTS_20260927.md)原文送达仍无收益，停止F/R提示家族。显式控制0/1→合同澄清1/1独立保留 |
| P12 | 论文级质量—成本Pareto、错误边界、真实Agent脚本工作负载和复现交付 | [v25结果](MILAI_APPLICATION_V25_RESULTS_20260927.md)完成八条预冻结轨迹；短四臂7/9、7/9、9/9、8/9，中B1/A4为7/9、8/9，长7/9、9/9；Pareto/错误链/复现完成，Luna发布随本交付 |

全程还需覆盖§20–24的多对象/多版本/current冲突、short/medium/long历史及checkpoint边界；§28–30全部指标和完整成本；§43跨session、CRUD、restart、partial failure、无关交错、多用户scope的非benchmark工作负载。Product当前不改；迁移须满足§44。State–Attention、action grounding、Current Evidence Capsule、Jev均按原计划的证据条件决定是否启动，不将“可选”解释为必须提前实现，也不将尚未满足的主阶段冒充完成。

## 反思与进入下一阶段

每个失败结果包含Observed failure、Expected mechanism、Actual causal chain、First broken link、至少两个替代假设、通用修复候选、confounds、最小下一实验和Continue/Pivot/Kill理由。每阶段同时回答§32十项Reflection。

温度一例成功不允许进入formal。当前版本进入请求不等于语义权威或实际被采用；snapshot风险不等于逐词因果。原始失败轨迹不能用后续最好轨迹替换。未见样本一旦参与方法修复即转development。

P6最终source mapping为`7ee904cba80c0facf0f513fe7607b15ea4fa5a61fc1a0553c1ef4e85144411e9`，使用独立P6R2锁。新增authority为模型可见协议干预，每生成额外39tokens；十三例66生成/67293tokens/929embeddingtokens/18exact reads。SER连续账本累计202生成/195740tokens/2837embeddingtokens/75exact reads，unknown/truncation/Judge均0。P5四次目标缩写失败、P6 R1冲突失败、P4中间虚称search都保留。没有整体成本下降或unseen收益结论。v20延后包装项已由P5一次成功构建闭合；P6R2新锁的打包随P7新入口统一完成，不重复旧构建。

总体完成要求以原1422行计划逐项核对：实现、条件判定、分阶段运行、成本、最终研究结论/复现、Luna发布和远端核对均有当前证据；本表的状态不能代替证据。

P7 R2后连续SER为360生成/332460tokens/3902embeddingtokens/75get；0未知/截断/Judge。方法未收敛，master仍ACTIVE；先做独立条件authority修复，然后按§25逐项冻结，继续P9–P12。

P7 R3/P8后连续SER415生成/373013tokens/4370embeddingtokens/75get；0未知/截断/Judge。49/55实际空证据请求省略authority，20首request与B1相同仍有d11漏搜。进入预注册三臂正式小规模比较，基于结果判断收益或pivot；Formation/Reconciliation和非benchmark真实脚本继续。

P9后连续SER568生成/530611tokens/5057embeddingtokens/75get。本轮42公开消息机会中37完成、4容量失败、1skipped，原业务checker分别计分。三臂21条早期约定观察均未形成记忆；12个依赖任务2次正确/6次错误退款/4容量失败。没有主方法自然适应证据，PIVOT优先级至P11，并继续P10资源/边界与P12真实脚本、Pareto和复现交付，不结束master。

独立Formation R1/R2和显式保存能力控制后，连续602生成/550151tokens/5187embeddingtokens/75get。两个静态cue均未带来形成收益；当前公共CRUD/Store能力控制通过。保留所有费用，先检验一次最小事件提醒及临时工具反例，不继续措辞堆叠或基础设施重跑；R、P10/P12仍继续。

Formation R3后连续614生成/557521tokens/5216embeddingtokens/75get。三次事件提醒准确送达仍0/2形成，原四例2/4、新增临时工具反例1/1；按预定停点停止F cue家族升级。继续独立R、P12非benchmark脚本和错误/成本边界；P10第二模型资源问题仍保留，master ACTIVE。

R1与明确用户要求的update控制后连续650生成/586650tokens/5770embeddingtokens/75get。原R/B1均2/3，业务成功但记忆pending不改；控制实际update证明组合调用路径可用，却无证据扩展至received。严格失败保留，先做一次最小任务合同澄清，P12开始持久副作用/重启/多scope应用方案，全部仍按轻量实例推进。

唯一合同澄清控制通过1/1，原失败保留；连续656生成/591982tokens/5884embeddingtokens/75get。R1方法仍2/3，不能混入能力控制成绩。接着只做一次独立原content候选呈现试验，再进入P12有状态应用和同域质量—成本边界；P10/master仍未完成。

R2原content试验已完成，严格2/3、必要更新0/1，两次提示四条原文均实际送达。停止F/R提示家族；连续671生成/604171tokens/6104embeddingtokens/75get。接着开发P12五阶段/九消息的持久应用，冻结B1/A3/A4/A5同域短脚本，再做必要历史边界；不继续措辞试探、重复CRUD检查或扩大benchmark。P10第二模型缺口仍保留，master ACTIVE。

P12 v25开发和八条冻结运行已完成，连续837生成/983553tokens/8948embeddingtokens/107get。八条均保留部分失败副作用、同ID恢复、用户隔离及删除/保持；Host70/72、严格62/72，不能当作独立样本汇总收益。short A3/long B1容量失败、A5错key、medium两臂虚构业务ID均保留。全部八条phase0/4首wire逐字段相同，fresh-session轨迹差异解释部分质量与费用差额。源码不变，§38/39条件未触发，无追加模型调用。Luna发布结果、复现和证据表；P10第二模型及其他外部matched比较未完成，master继续ACTIVE。

v25已发布并核对远端`5e49cf9a7a2cc6eef78f0b76c089c2f1c95e70a8`。P10源码核对发现固定Mem0原生ADD-only语义不等于v25同IDrevision，因此不伪造同源CRUD比较。转向独立v26原四例形成任务：两臂各六消息、相同实际用户/业务任务与rubric，原生user+final assistant自动摄取、公开管理/搜索接口，完整计入额外模型成本。先薄适配开发/窄验证/冻结，再真实运行；第二模型资源问题不阻塞这项独立工作。

v26原四例外部系统切片已完成，源码mapping`37e57b17808d9378111032de11ba66960280620586b1a2a9586e4e81aaffc4cb`，Luna开发提交`2968f75`。Mem0形成2/2、later2/2、strict4/4；B1均未形成，strict2/4；两臂临时不误存。实际官方SDK/HTTP/持久化链条闭合，无确定性适配错误；Mem0额外六次默认抽取50102tokens，总成本53852对5324。保留全部成本，不将系统差异归因SER，不追加暴露样本调参。连续863生成/1042729tokens/9617embeddingtokens/107get。P10外部比较已交付，第二模型族仍NOT_RUN；广泛扫描条件不成立，Product NO-GO，master ACTIVE。
