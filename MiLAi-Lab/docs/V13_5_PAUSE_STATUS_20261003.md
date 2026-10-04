# v13.5 暂停与 GitHub 检查点

2026-10-03 按用户“暂停当前实验提交到github上”的明确指令，实验目标为 **PAUSED**。
完整 F0–F4 / L0–L4 / FUNC-01–16 尚未完成。当前没有实验请求在运行；
不启动 r5、不继续 L2–L4，恢复需用户明确指令。Product 仍为 **NO_GO**。

本次提交保存已实现代码、测试、配置、失败与费用摘要，作为可审查的草稿检查点。
它不表示功能验收通过，也不合并 main。机器快照见
[暂停清单](../data/manifests/v13-5-pause-summary-20261003.json)，各轮完整计数与证据哈希见
[cohort 记录](../data/manifests/v13-5-runs.json)。

## 已实现与已验证的边界

统一入口 `tools/run_functional.py` 复用实际 LangGraph Agent、SQLite Store/Saver、
MemoryService 和既有计账 provider。`functional_v1` 是显式启用的 Lab profile；
历史默认路径继续保留。

- 原事件先捕获；模型选择程序发行的真实片段句柄，程序从原文提取引文。
- 同 ID 局部修订、未改字段继承、no_change、撤销、版本读取及快照分页已实现。
- 遗忘传播覆盖选中来源和实际暴露的助手输出；缓存及完成／中断 checkpoint 的重放需检查可见性。
- 预订—标签与文稿编辑—审批—发布复用实际本地业务后端，区分执行、回执捕获、投影和交付；未知修改先查询，避免盲目重放。
- 每消息调用额度跨重启持续；实际完整请求参与容量核验，有限队列与原连续费用账本分别记录。

这些机制有 scoped 机械检查和实际 SDK 证据，但真实模型尚未通过正常功能门槛。
实际提交、引用身份正确和摘要语义受支持是不同结论；程序没有语义真值判决器。

## 实际 L1 结果

每轮都保留原 24 案／48 条消息分母，不能拼接各轮最优结果。
`COMPLETED` 只表示入口返回，不表示答案或语义维护正确。

| 轮次 | 实际消息 / 未运行 | 原 rubric 与停止原因 | 调用 / generation tokens |
| --- | --- | --- | --- |
| r0 | 17 COMPLETED / 31 NOT_RUN | 8 PASS、2 FAIL、14 未运行；重复建记录、历史查询改坏当前值、正文与 scope 矛盾 | 36 / 179,274 |
| r1 | 35 COMPLETED / 13 NOT_RUN | 16 PASS、2 FAIL、6 未运行；临时保存假确认，以及一条最终答复只有左花括号 | 59 / 264,223 |
| r2 | 4 COMPLETED / 44 NOT_RUN | 仅两案定向检查；原 rubric 条件通过，但续办未实时查询，v13.5 当前状态要求失败 | 7 / 36,863 |
| r3 | 1 FAILED / 47 NOT_RUN | 最终回复只有 reasoning、content 为 null；业务和语义提交已经发生，原效果保留 | 4 / 23,896 |
| r4 | 25 COMPLETED / 23 NOT_RUN | 12 PASS、1 FAIL、11 未运行；raw 搜索命中被误报为语义保存，停止；另列修订直接证据不足 | 50 / 269,980 |

r4 的 `update-3` 保留原 rubric 的身份／正文／历史 PASS，同时记录 v13.5 direct-support 失败：
新值只引用旧值的原文，当前修正仅在 trigger binding 中，不能充当字段证据。
`recall-3` 没有任何语义记录或写入回执，却声称已保存；后续从 raw 回答正确不抵消该失败。

## 暂停时的 r5 候选

已落盘的 r5 修改明确区分只读 packet 中的原文片段与实际交付的语义记录，
报告本页真实数量；新 metadata 计入材料预算。每次模型调用前附带当前消息实际成对
调用／回执的无正文摘要，区分提交、未变、失败、未知和待返回操作。
写入说明明确要求所选片段直接支持新内容；trigger binding 仅是执行归属。

25 项 memory 检查、17 项完整入口／隐私重放检查已通过，相关 ruff/mypy 通过。
完整请求、恢复后提交摘要及零额外保存／HTTP 的机械路径得到检查。
这不是自由文案成功声明的语义拦截器，也未证明已修复真实模型失败。
**r5 未创建 input freeze，模型请求为 0。**

此前检查包括实际外部 SDK 生命周期 4 项、既有 native 桥接与容量 24 项，以及较早版本的
受影响 memory、应用和源归属检查；详见 [L0 记录](../data/manifests/v13-5-l0.json)。
这些测试集合有重叠、版本也不同，不相加成一个最终通过总数。
本次暂停发布只补文档／哈希／边界检查，不继续模型实验。

发布检查中，全量 ruff、两个改动模块的 mypy、CI verification matrix、工具边界、
diff 检查通过；64 个 JSON、65 条本地链接和 15 条证据哈希核对通过。
**活动 Lab 分层检查未通过**：`application/functional.py:265` 直接导入
`memory.functional_state.note_exposure`，产生同一 import 的两条 `LAYER_IMPORT`。
该实现问题作为暂停时已知 debt 保留，未为通过检查放宽规则或继续修改运行时。
它不涉及 Product／Archive 改动，但意味着本草稿不能声明完整 CI 或依赖边界通过。

## 未完成事项

- L1 22/24 门槛未通过，假保存与直接证据问题的候选修复尚无新模型证据。
- Lab 应用层到记忆内部模块的依赖违规尚未修复；需恢复后调整职责边界并回归。
- L2 两工作流 12 案／26 消息的输入已准备，真实运行未开始。
- L3 的 57 个形成请求与 30 个读取问题输入已准备，真实运行未开始；两者是不同单位。
- L3 公共输入可复现 builder 的拆分尚未完成，暂停时的未验证清单仅保留在本地 ignored 草稿。
- L4 尚未创作、读取或运行，不能声称未曝光功能确认已完成。
- 140 项新要求尚未完成逐项终态回填；原 48 项字节与状态保持，不自动升级。
- 同族开发审查不构成独立 Judge；原文引用、Source hash 或记忆 ID 不提供业务授权。

## 费用与证据保存

v13.5 新增 **156 次 generation / 774,236 tokens**，known 与 charged 增量相同；
新增 embedding 和 unknown usage 均为 0。reasoning 已在 completion 中计入，不重复相加。

连续账本暂停读数为 9,882 次 generation、28,466,522 known tokens、
28,496,909 charged tokens、964,645 embedding tokens。
历史 unknown usage 为 1，对应 30,387 保守计费差额，本阶段未新增。
账本 SHA256：`b18fae7fa71c3862eb4e0fc336b0021fa5b4928d89275f71ce55b6ec92973edc`。
原 limits 和历史链不重置。

Git 保留源码、测试、配置、说明与紧凑证据哈希。原始请求／响应、数据库、checkpoint、
copied corpus、未完成 builder 草稿与失败产物保留在原本地 ignored 路径；不提交这些大体积原件。
原 v13.4 最终结果、失败、评分与 Simplify 退出均保留，未恢复 T1–T3。

## 发布范围与回滚

分支为 `feat/lab-functional-v13-5-20261003`，基于本地 v13.4 终态
`1d8cc7e414d0df728215c1ad5d0cbc82b0ac6398`。
此前 v13.4 尚未推送，因此这次分支与草稿 PR 也携带其历史提交。
PR 以已有 v13.3 分支 `feat/lab-edm-cep-v13-3-20261002`
（`2319401bc0c6f29142cdf139a09b22576c0da1c5`）为 base；保留原 PR80，不修改历史分支。

改动范围为 Lab 和 Lab 对应 CI job。Product／Archive 无改动，不修改 Product
Schema、API、权限或 Canonical 行为。Lab 增加 opt-in 工具及读取／回执合同。
回到 v13.5 前版本可检出 `1d8cc7e414d0df728215c1ad5d0cbc82b0ac6398` 到独立 worktree；
运行开关见[用户指南](V13_5_FUNCTIONAL_USAGE.md)。保留当前 Store 与失败证据，
不要用旧源码继续运行被冻结的新 cohort。

未来恢复时先核对暂停快照、实际源码、SDK、原 ledger 与服务身份，再为候选建立新冻结。
不能原地修改或重新解释 r0–r4，也不能仅凭本次机械检查宣布完整功能通过。
