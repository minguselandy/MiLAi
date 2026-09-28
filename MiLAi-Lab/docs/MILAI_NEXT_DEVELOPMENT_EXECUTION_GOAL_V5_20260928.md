---
status: EXECUTION_COMPLETE_PUBLICATION_VERIFY_REQUIRED
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
plan_sha256: ff79dcd0e24458175c520913bac29b842a69b5ebbc15681545748b14b2eb52a2
baseline_report_commit: 676fe4d32005cefbfb01daa4fe24425edf5a5e21
baseline_method_commit: 24ef49945cd12eccbd85792fee3c256bf3fe6d2a
accepted_method_commit: ec682a3a8b1ac58b41733b882ed0bad367347fed
bounded_small_sample_gate: PASS
research_goal: NOT_ACHIEVED
second_model_family: NOT_RUN
product: NO_GO
---

# NEXT_DEVELOPMENT v5 执行记录

**v5 规定的开发、冻结评估及 V9 完成审查已完成；最终发布需独立核对远端 SHA 后，由实际线程 Goal 标记完成。**
全部结果、费用、失败、局限与复现见[总体报告](MILAI_NEXT_DEVELOPMENT_V5_OVERALL_EXPERIMENT_REPORT_20260928.md)。
本记录随报告发布，提交自身不预先声明已核对自己的远端 SHA；发布完成以 PR/本地忽略回执和线程工具状态为准。

用户实际 Goal 明确要求完整阅读并执行[v5 计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v5.0.md)。
Root 完整读取 1,204 行，原 DRAFT/PAUSED/NOT_STARTED 字节保持，授权来自后来恢复的 Goal。
此次恢复撤销旧 v4 暂停对新任务的限制，不预设任务结束自动暂停。
当前小范围验收通过不等于长期研究总目标完成；Product 仍 NO_GO。

当前树 `/cra/memory/mx_memory/MiLAi-worktrees/next-development-v5`，分支
`feat/lab-obligation-contract-v5-20260928`，基于已发布 v4 报告。
原 main、旧树/草稿/失败/分数/锁/账本保留，不合并 main、不恢复 v27。

## 完整要求与验收

| 项 | 交付与状态 |
| --- | --- |
| V0 / §6 | COMPLETE；50 项来源身份，6 脚本、12 轨迹/30 答/44 请求；v4 两轮旧分各 5/6 不改 |
| V1 / §7、20.1 | COMPLETE；四层义务、人工用户可见依据、20 个去重窄检查、两次实际离线 CLI；rubric 不入 runtime |
| V2 / §8 | COMPLETE；每版本六脚本合计 55 项，两版本共 110 项人工链；legacy/diagnostic 分列 |
| V3 / §9、16 | COMPLETE；66 个冻结 HTTP 的九类组件分析；JSON 空白候选只离线测量，未部署 |
| V4 / §10 | COMPLETE；10 脚本/27 消息/133 义务，覆盖所有必需类别，输入先冻结 |
| V5 / §11 | COMPLETE_WITH_FAILURE；原 v4 R2 runtime 首轮 9/10、显式70/71、持久59/59；H 首断点为 CURRENT_TASK_CONSUMPTION |
| V6 / §12 | 无独立分支；V7 单候选的完整十脚本回归及两条新当前约束覆盖接口修复要求 |
| V7 / §13、20.2 | COMPLETE；候选四次诊断门槛通过后执行预冻14 jobs；候选12/12、显式89/89、持久67/67、任务156/156，world/历史反向分别通过 |
| V8 / §14、20.3 | NOT_TRIGGERED；全部131次生成走all，最多6记录/351candidate tokens，无实际检索瓶颈 |
| V9 / §17–20 | REPORT_COMPLETE；完整成本、失败/两解释/反思/局限/复现均已整理；Luna发布后Root核对远端再完成线程Goal |

§5 的条件 V7 不免除 §10/20 的基本 world/assistant 覆盖；R1 已真实测试两者，H 失败才触发修复。
V3 离线成本候选没有进入首轮；V0–V5 的 161 个现有 runtime/runner/package/lock 字节保持。
旧 R2 field_plan 三个点名字段正确但额外完整性有歧义，作为 diagnostic 保留，不改旧 fail，不据此继续措辞微调。

## 唯一修复与实际结果

[R1 结果](MILAI_NEXT_DEVELOPMENT_V5_PROSPECTIVE_R1_RESULTS_20260928.md)保留实际更新 Store9、完整交付9、旧历史6仍在却答6的失败。
竞争解释为呈现线索竞争与模型当前/历史消费不稳定；不能只归因 assistant，旧值也在 user/tool proposal。
Astra 仅处理这一具体冲突；Sol 实现一处通用 opt-in 请求副本移位，Root 冻结[两阶段协议](MILAI_NEXT_DEVELOPMENT_V5_AUTHORITY_R2_PROTOCOL_20260928.md)。

候选将单份相同 Durable Memory 材料从首 system 移到实际 current user 标签之前，原 checkpoint/历史/工具 JSON 不变。
这是位置＋承载 role 的组合变化；默认仍 system，不增加 controller/持久状态/强制read/长提示。
17 项窄测、默认三路径字节对照和静态检查通过；源码 Fast CI 36391234190 success，Full skipped。

诊断 system 当前0/2、历史0/2，候选各2/2；全部形成/更新/范围正确，按预冻门槛进入完整确认。
候选十个已暴露脚本10/10、两个新内容2/2；新内容 system 0/2，当前/历史值均错但持久状态正确。
所有初始失败保留，无语义重试。COUNT 省略式一句的格式解释及精确答案已在总体报告披露，两臂一致评分。

## 成本、职责与收口

Root 负责所有真实 HTTP/评分/成本，HTTP 并发1；Sol xhigh 唯一源码负责人；Luna high 授权 Git 发布。
没有新模型、服务、Judge 或 controller；Host/vLLM 参数与公开工具不改，Product NO_GO。
同42个固定R1请求离线移位的输入差均0；真实回归成本降低不能解释为压缩，DELETE少一次搜索等轨迹差异保留。

连续账本为原树 `artifacts/ser-v20/budget.json`。
起点2994 generation calls /3,785,491 generation tokens /21,237 embedding tokens；
本轮131 generation /185,863 tokens，53 embedding /984 tokens；
终点**3125 /3,971,354 /22,221**，SHA
`98b02945ab195ad94e37061f97c5ba5eb8068ecd87ff47caef9f76f9e51fdd15`，历史字段未重置。
28 jobs/86公开消息全部完成；前置Git身份失败及零模型reprepare保留，全部费用见[总账核对](../data/manifests/next-development-v5-total-costs-20260928.json)。

GO 仅接受此冻结小规模研究 recipe；本轮停止增加实验。长期目标 NOT_ACHIEVED，第二模型 NOT_RUN，Attention NOT_TRIGGERED。
下一项研究需新的明确任务；旧 ACTIVE、原计划或协议的 NOT_RUN 不构成继续授权。
