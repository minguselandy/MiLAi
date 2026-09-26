# Reconciliation R2：原正文已送达，停止该提示家族

[唯一原正文候选方案](MILAI_LIFECYCLE_V24_RECONCILIATION_R2_PLAN.md)完成三个实例、六条公开消息，严格2/3。成功发运后仍未更新pending记忆；失败动作保持pending、无关成功动作不改记忆，两个反例通过。四条候选原content在两个合格请求中逐字送达，但act阶段仍零manage调用。按预定停点停止F/R提示家族，继续P12持久化应用，不再追加措辞或重复CRUD能力检查。

这是一个新R2运行，与固定历史B1/R1参考比较，**不是fresh matched或未见评估**。旧R1两臂均2/3；显式用户update控制首次0/1、唯一合同澄清1/1全部保留，不能混入自主R分数。[机械明细](../data/manifests/milai-lifecycle-v24-reconciliation-r2-r-results.json)保存实际调用、合成正文和回执；[语义汇总](../data/manifests/milai-lifecycle-v24-reconciliation-r2-results.json)记录本轮判定与累计费用。

| 指标 | R2 |
| --- | ---: |
| 严格case / action-memory consistency | 2/3 |
| 正确seed entry | 6/6 |
| 正确业务动作及结果报告 | 3/3 |
| Host完成消息 | 6/6 |
| 成功相关动作后stale-current | 1/1 |
| 被错误修改的原entry | 0/6 |
| act阶段manage / 不必要maintenance | 0 / 0 |
| 合格实际marker / 原content候选 | 2/2 / 4 |

Root依据实际HTTP尾部、已完成journal、动作生成request的FULL材料和EXACT scoped search绑定独立重建候选，再核对首system原字节。15个请求、15条工具材料全部正确绑定；ok:false不触发。候选包含无关访问事实，程序不判断语义相关性。业务成功后直接final，原六条记忆全部保持。零误改与零必要更新不能证明选择性有效。

## 成本与实现边界

R2为15生成，11555输入+634输出=12189tokens；9次embedding/220tokens；unknown/truncation/Judge均0。相比固定历史R1多150tokens、B1多446tokens，没有质量提升；动态UUID/时间/namespace和输出轨迹不同，不能将总差额全部归因于正文。离线从实际请求移除marker测得直接输入增量218+211=429tokens，R1对应305tokens。

15次projection合计CPU2892557ns/wall2429280ns；程序Store读、自动写和独立模型阶段均0。观察层另有12次Store读，CPU63139929ns/wall1111977583ns，不混入版本resolution读。Provider wall6.975秒、进程13.203秒；单次时间不是稳定性能结论。trace531778bytes、sidecar163840bytes、checkpoint184320bytes。

连续账本为671生成/604171 generation tokens/6104 embedding tokens/75 exact version-resolution reads。整个v24含全部F/R候选及能力控制共103生成/73560tokens/1047embeddingtokens；历史失败不清零。R家族及其控制共57生成/46650tokens/888embeddingtokens。

77文件mapping `48b85054f8fb39e6363c7d594367579f350e3a2147e0cb146a68823eb46c3066`，R2 lock SHA `ea702b127ae8506e6c8844ca60c3c6ec18e8204f9e7f533a10d8bb23594bec12`。适配器仅增加默认false的`include_content`选项和新臂接线；R1默认不变。三项窄检查及最后受影响两项复核、ruff/mypy、一次sdist/wheel构建通过。没有Product API/Schema/权限/Canonical变化，也没有旧M1/ODR或vLLM设置变化。

## Failure Review

Observed failure：业务实际成功，但已有记忆继续声称尚未发运。Expected mechanism：候选原文和真实回执共同进入请求后，普通Host准确更新相关entry。Actual chain：准确seed→FULL/EXACT检索→正确发运→成功回执→首system候选原文→直接final。First broken link仍在普通Host的更新操作选择。

H1“仅有引用造成正文关联负担”不足以解释全部失败：复制原content后仍不更新。H2“系统层一般维护要求未成为实际操作目标”仍与结果相容，明确用户任务控制支持这种区分，但不能推断模型内部机制。H3“工具或Store不可用”被此前真实update控制反驳。原文回查困难可能存在，但本轮没有证据支持其修复收益。

未增加强制CRUD、循环或自动语义改写，因为这会改变普通Host自主决策的研究问题并引入额外成本。当前最小下一步是P12：沿用冻结SER，在独立有状态应用中检查实际副作用、重启、多个用户和显式用户记忆操作，报告质量与全部成本。应用不能把显式用户update冒充自主Reconciliation。Confounds仍包括单正例、已暴露合成任务、固定历史对照和模型路径差异。

## Reflection

1. 支持：实际业务回执与此前送达的scoped原正文可低开销关联。
2. 反驳：附上原正文足以修复本例的动作后更新遗漏。
3. 第一断点：普通Host没有选择manage_memory。
4. 简单解释：明确用户任务与一般系统维护要求的执行不同。
5. 简单方法：保持上游CRUD，应用中的明确保存/更新需求直接作为用户任务。
6. 复杂度：适配器虽小，未体现收益，不默认启用。
7. 过拟合：停止围绕单正例继续换词，不引入领域匹配规则。
8. 反例：失败与无关成功两例保持，后续应用增加真实partial failure和用户隔离。
9. 决定：Kill当前F/R提示家族；Continue独立P12应用。
10. 原因：机制送达充分、重复缺少行为收益；总目标尚有应用、成本边界和第二模型证据缺口。

## 复现和交付

使用本checkpoint的源码、R2 lock/config和[执行冻结](../data/manifests/milai-lifecycle-v24-reconciliation-r2-execution-freeze.json)中的路径/SHA；输入与rubric直接复用R1，运行器不读rubric。运行入口为`tools/run_milai_lifecycle_v24.py`，臂`r_post_action_content`。本地DSN仅经环境注入，使用全新run_id/namespace和产物目录；保留原运行费用，不覆盖执行锁或结果。F1/F2/F3和R1复现应checkout各自报告的源码checkpoint，不能让新文件冒充旧source mapping。

生命周期开发小阶段收敛为负面结论；Luna负责此checkpoint提交和远端核对。P10第二模型和P12应用/质量—成本交付继续，总Goal保持ACTIVE。Product迁移条件未满足。
