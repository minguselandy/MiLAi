---
version: v17.0
date: 2026-09-26
status: COMPLETE_WITH_M1_LIMITATIONS
reference_commit: 3676c511f4c4087453d5bbf54cea3514e57fd948
scope: MiLAi-Lab
method_scope: M1_SPARSE_EVIDENCE_GROUNDED_DECISION_STATE
---

# v17 M1 开发记录

已完整读取用户指定的 [1553 行计划](MILA_LANGMEM_M1_V17_DEVELOPMENT_PLAN_20260926.md)及当前仓库边界，以 v16 交付 commit `3676c51` 开始。用户原计划文件保持原字节，SHA `88eab77766ab8ff22730d653f7140a3476aedfe208f816b3c388604054ba1883`。执行要求转入 [Goal v17](MILA_LANGMEM_M1_GOAL_v17.md)，没有将任务缩成规划或单一 fixture。

## A / M0：底座与费用

已逐项核对 v16 27 份 runtime、6 份验证身份、B1/foundation lock、reference/final-freeze/results、原数据和封存 v16 账本。[新 reference](../data/manifests/milai-m1-v17-reference.json) SHA `e01b1ca27dc68730d6a24dce6000dbbf914e26e502bea745b61fda026fecb5f7`，27 份源码另存 ignored `artifacts/langmem-m1-v17/v16-reference-source/`，作为必要默认分支比较的已知输入。旧 lock 与结果不更新散列冒充新实现。

原 vLLM 容器仍运行，实际 image、command、环境 hash 和 HostConfig 与 v16 一致；证据 ignored `environment-before.json`。沿用原 Qwen3.6-35B-A3B-FP8、bge-m3、隔离 Lab Postgres、4096 输出、65536 上下文和并发 1；不更换服务，不增加 parser 参数。

独立持续账本 `artifacts/langmem-m1-v17/v17-budget.json` 从零新用量开始，引用 v16 的 55 次生成／40072 tokens／443 embedding tokens，以及更早 v15 封存历史。累计 caps 为 null，每公开消息 12 次尝试继续沿用。开发模型由已有一名 Sol xhigh 负责，root 统一真实请求、freeze、数据、费用和报告，Luna high 负责授权发布。

## 最小实现落点

新 `methods/milai_m1` 持有独立 Basis SQLite、纯 reducer、Evidence View 和程序 recheck。原 Provider 加 opt-in hook，把 delta 与 calls/answer 放在一次 generation；原 Agent/runner 只做必要上下文与恢复接线。沿用原 diagnostic/MERIT 循环，不复制 runner，不导入旧 contextual 方法。

第一次 adoption 绑定该 generation 实际请求交付；continued exact refs 只表示延续采用。程序只标 revision/tombstone/task 变化，不做 semantic invalid、自动 latest 或强制行动。非法 delta 留下明确拒绝记录，同响应工具零执行；不增设自动语义重试/审批层。空 gap 不自动 clear，完全相同 set 不增加语义 revision，ack 与 state change 分开。

## V1 受控输入预冻结

在任何新真实模型请求前已冻结[一个机制 fixture](../data/fixtures/milai_m1_v17_mechanism.json)与[manifest](../data/manifests/milai-m1-v17-mechanism-freeze.json)。3 个公开消息，同一个待定 packing task：从已有记录读取 crate Lumen-42 的 holding instruction，等待用户批准，最后通过本地模拟工具记录。值和工具 schema 只在 fixture，不进入通用方法规则。

fixture 先通过真实 upstream manage_memory seed 温度 4°C 的 X@1，在第一个公开消息完成后无条件更新同 UUID 为 8°C／X@2。seed/update 是显式 `FIXTURE_CONTROLLED_*` 外部操作，有独立 origin/call/operation 证据，零 Host generation，不伪造 Observation 或 Decision Basis；它们不是普通 Agent 策略，也不被算成自然 Host 更新。

第二条用户消息不透露变更或新值，实际程序 recheck 应进入下一次普通请求。若 Host 没有自然 adopt 初版，或没有在重核时得到新版，原样报告 NOT_REACHED，不靠 fixture 填入 Basis 或强制 search。最后是否按 8°C 正确执行仅由独立 rubric 核对，模拟业务函数照原参数执行，没有正确值硬门禁。

fixture SHA `885024dd97c33addee0854b9c0e4293f44595d7f04a9859d7e522060a9acea67`，manifest SHA `d760e5b809f3bb8b53c12a0f728c578bd83f412f9237805ac444b14d0ce1a8ee`。评分规则在 ignored `mechanism-rubric.json`，不交给 runner；永远属于 development，不计 benchmark 或方法收益。

## 指标口径与顺序

[离线评价协议](../data/manifests/milai-m1-v17-evaluation-protocol.json)也在零请求时冻结。主要 activation 采用接受 delta 后 Basis 存在的 model turn 比例，另报生成前 Context 占用；null 可能保持旧 Basis，不能只数 set。semantic revisions、identical no-op、clear、ack、recheck projection 分开。adoption 验证准确材料交付/续用，selectivity 同时给实际候选数和采用数，gap/task-summary/普通任务干预作有限人工含义复核。

| 阶段 | 当前状态 |
| --- | --- |
| A / M0 reference、Goal、原服务与封存费用 | COMPLETE |
| B–G store/evidence/adapter/recheck/recovery | COMPLETE；38 文件 mapping 已冻结 |
| 当前 decoder 必要 probe | PASS：3/3 原服务生成 |
| V0 确定性窄检查／默认 B1 合同 | PASS：7 项 M1＋1 项 B1 parity，静态与边界通过 |
| 新 M1 lock 与 final freeze | COMPLETE：最终为 R2，下文保留 R1 修复历史 |
| V1 受控机制链 | R2 TERMINAL；真实 recheck 未完成，旧值动作保留 |
| V2 原 12 例／20 会话 | COMPLETE；语义 5/12 |
| V3 原 arc0／5 集／7 消息 | COMPLETE；native 4/5、dependent 1/2 |
| 全指标／费用／GO-PIVOT-KILL／发布 | 结果与成本已完成；PIVOT，Luna 发布交付 |

后续按实现／必要 decoder probe → V0 → final freeze → V1 → V2 → V3 执行。所有失败与费用保留；没有新 seeds、M2/Attention、独立 reflection call 或真实 B1 全套复跑。

## M3 decoder 与接线进展

第一版 Evidence View 暴露完整 UUID/hash，且多个业务回执缺少对应标签。对照计划 §6/§9/§11 后在真实 probe 前改为 e0/e1 的请求内冻结映射，continued 为 c0 等；实际字段仍由 B1 completed request 的正文/hash/exact ref 校验。Context 标注 current user、工具消息位置或 memory item，并显式区分 new_observation_refs，不复制正文。

Root 在原部署完成 3 次最窄 decoder probe：set＋两项有序 calls、clear＋answer、null＋answer，均与指定 JSON 结构一致并通过 runtime delta 结构验证。证据 `decoder-probe-r1/report.json`，schema 文件 SHA `78df2f795886e09cd7449743dade42ffaab27ffb226652cc60c59c4ca9e41d33`。费用 2163 input＋117 output＝2280 tokens，0 embedding、0 工具执行、0 Basis 提交；它仅证明协议可生成，未冒充 adoption 或方法效果。

首条真实 Graph＋Mock Provider 的 V0 已通过：原 pinned create@1→search 交付→同代 set 采用 e1→受控 update@2→null 保留未核原因→正常 search 交付 @2→set 采用新版并 ack，冷读恢复正确。非法 delta＋合法业务调用也已验证明确 ERROR receipt 和工具零副作用；其余恢复／重放检查仍在完成中，尚未开始正式 V1/V2/V3。

## V0 与源码冻结

完整 7 项集中零模型测试通过，覆盖真实 Graph/上游 tools 的准确采用与重核、continuation、同文不同 Observation、非法 delta 零副作用、有序调用及原工具错误、幂等/恢复/任务隔离、无关版本与 tombstone，以及受控 fixture 的 completed replay。另 1 项原 B1 同输出 wire/world/checkpoint parity 通过。受影响 ruff、14 文件 mypy、99 文件默认 core mypy、两类活动边界与 CI YAML 解析均通过；无 LangMem 的模拟默认收集在 importorskip 正常跳过。

新 lock SHA `b887f84c84bf0b6c0c314225387e2ad2de30a7bdf512fdf908d7c6676b9534e7`，38 文件 source mapping `ff94284cccc3d8f75ba0c9e6433e30cb40f6f33688bb4c95477ac702551d2ee5`。正式三个 prepare 通过，机制 schema 和原 probe 对象一致，未增加 probe。sdist 新纳入 M1 lock，待一次必要打包后进入正式运行。

## R1 失败与 R2 通用修复

R1 在同一冻结源码上执行受控机制、12 例及 arc0。受控机制终止正常但语义失败：采用 X@1 后收到 @2 的程序 reason，未读取新版，重复原 set 后 clear 并记录旧 4°C；这不是 recheck 成功。12 例中 d02、d11 的第二会话和 arc0 第 2 集遭遇同一协议错误：模型生成 `{"op":"clear","decision":"..."}`。runtime 按既有严格合同拒绝，同响应工具未执行。诊断最终 10/12 例、18/20 会话完成；arc0 仅 1/5 集完成，保留完整原分母，不将中断当作普通语义评分。

根因是 generation schema 只约束 object|null，未表达 reducer 的字段要求。修复仅将 adapter 的 delta schema 对齐 null、仅 op 的 clear 和六字段完整 set；没有放宽 reducer、添加自动重试或改语义提示。一个直接针对形状差异的测试和相关静态检查通过。原服务追加 3 条与 R1 完全同文的 probe，全部通过，增加 2280 tokens。R1 源码／锁／freeze／日志和费用保留于 ignored 制品及[失败 manifest](../data/manifests/milai-m1-v17-r1-failure.json)。

R2 lock SHA `d03779620ab8a15c3da7902765b9e477af0207257f809046826e35ee80fceb02`，38 文件 mapping `392c14287062a92465f74b31e402ea65099a55cb5136a1c3939b05dd1655b66f`，最终 freeze SHA `e263aa177869abf63c1c4faaea55f7a9c00b77960ddf241e304a99f112ffc1df`。三组 R2 使用新空 namespace、相同原始输入，从头完整运行，不拼接 R1 成功片段。仅 schema/test 两文件变化，包声明未改，因此保留 R1 唯一 build 的包含边界证据，不声称它与 R2 源码逐字节一致，也不重复 build。

## 最终 R2 与结项

三组 R2 均完整终止，协议拒绝 0。累计 v17 101 次／101810 tokens／916 embedding tokens，全部历史和失败保留；R2 正式 53 次／56099 tokens。离线逐条核对 22/22 接受采用与实际正文/准确身份，activation 21/53、semantic set revisions 14、recheck trigger 1／projection 2／ack 0。受控业务仍按旧 4°C，未用硬门禁遮蔽。14 个不同语义 set 中 9 个为任务/主题标签，非干预 3/4；诊断语义 5/12，arc0 native 4/5、dependent 1/2。完整分析见[最终结果](MILA_LANGMEM_M1_V17_RESULTS_20260926.md)，结论为 PIVOT、M2 NO-GO。

收口发现 deferred 与 task notice 的分支缺少直接断言，补一次隔离零模型检查，验证冷恢复、新 Observation、任务返回 ack 及 @3 再触发；明确标记为 R2 后验证，没有改源码或正式轨迹。最终38份源码、原计划、旧锁/账本及原 vLLM image/command/environment/HostConfig 再核对一致。所有 raw trace/DB/private 配置保持 ignored，Luna high 按既有授权负责最终提交推送。
