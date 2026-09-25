---
version: v13.0
date: 2026-09-25
status: COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT
baseline_commit: 4ea47639e6fe0be037c5b052459e03814be8531d
scope: MiLAi-Lab
---

# v13 后续工程开发记录

[Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v13.0_20260925.md) 先补当前模板的正式入口及失败处理提示，再以最终源码做有限连续验证。v12 已验收功能保留，不重复开发。

## 基线核对

开始时本地 HEAD 为 4ea4763，工作区干净。已提交的 49 份运行文件与 v12 最终映射 f39d8170f168a56d21057a3079fdaed21a5cb6d32e852687544dd740df8955d0 全部一致；v12 结果清单中的 34 份本地制品散列匹配。核对使用已提交源码，后续有意修改以新映射区分。

v12 的 38 次生成／323992 generation tokens／2383 embedding tokens 封存。v13 使用新账本，失败及恢复连续记账，历史前缀不重复计费。

## 已完成实现

| 位置 | 修改与目的 |
| --- | --- |
| contextual_host.py | memory_save 的 preflight/core 拒绝回执直接给出真实 failed_operation_id 和 repair_of 用法；成功提交后若仍有未决失败，提前说明合理终结与继续修复的选择 |
| prepare_contextual_v9.py | 正式接纳当前 v12 notes 模板，冻结该模板，沿原生输入和模型身份准备 |
| run_contextual_merit.py | 接纳 react_notes_v12_off，严格核对 maintenance v4、ordinary/notes/off、无额外控制和 thinking=false |
| 现有窄测试 | 实际 JSON-action/notes 及 native 交付接线、失败不被自动清除、首次合法终结；当前模板真实零模型准备及错误控制配置拒绝 |

运行协议、request schema、磁盘格式和 Product 行为未变。只增加 Host 回执中的 repair_guidance；它使用现有维护事实，不写新账本、不触发额外模型调用。同一卡成功不能清除无关失败；仅为补 repair_of 而重复已提交写入也不是要求。Host 仍需判断旧提案确被提交取代、合理放弃或保持 pending。

本轮没有 sidecar 协议变更、State 新策略或 Attention 比较。当前工具名 prepare_contextual_v9.py 沿用，为兼容已有命令不复制新 runner；其 template 参数已经可以准备 v12。

## 检查

| 检查 | 结果 |
| --- | --- |
| test_contextual_turn_maintenance.py ＋ test_contextual_runtime_recovery.py | 28 passed，包含 JSON-action/notes 新回执实际到达下一请求 |
| test_contextual_v9_prepare.py ＋ test_contextual_merit_adapter.py | 10 passed，当前模板生成原生同一 arc，零模型调用，错误维护协议与控制配置拒绝 |
| 修改源码与测试 Ruff | 通过 |
| Host、prepare、MERIT runner 的 mypy | 通过；曾暴露版本分支变量类型推断冲突，改用收敛后的明确 arm 变量解决 |
| git diff --check | 通过 |

两组测试文件不重叠。没有全量测试、打包或新包依赖；未更改生成参数 schema，所以不重复 v12 的 decoder 探针。真实运行不能由模拟测试替代。

## 真实验证安排

固定已暴露的 arc0-000，五集、七条公开消息、两集 dependent；从空记忆与原始世界开始，保持原生数据、工具、checker 与 session 边界。单入口模型并发 1，沿用 Qwen3.6-35B-A3B-FP8 / bge-m3、thinking=false、4096 输出及每条消息十二次响应。

Host 与 embedding 的只读服务查询已确认模型名及上下文长度分别为 65536／8192；没有通过该检查调用生成或 embedding。正式准备重新生成模型文件身份和新的源码映射，准备完成后才开始真实实验。

最终结果另写报告；没有运行完前不预填成功。若无自然写入拒绝，新提示的节省只能保留为待证实，不能因窄测试成功就认领真实模型收益。

## R1 连续运行与有依据的后续修复

R1 已从原始世界、空记忆完整运行五集、七条消息。原生 4/5，dependent 2/2，Host／维护 7/7 complete。新增 29 次生成、176986 输入＋4069 输出＝181055 generation tokens；九次 embedding 共 1574 tokens，unknown=0、Judge=0、截断=0。无自然写入拒绝，未以此声称 repair_guidance 节约了真实调用。

原生失败在独立退款 episode 3：Host 读到审批阈值，未退款，仅发送客户消息，却在最终回答中声称已经升级审批，没有对应工具回执。保留原生失败，不改政策、业务工具或评分。当前两卡均有正确新金额及执行完成状态，但正文仍含临时 mN 指代，作为语义限制保留。

进一步核对发现 episode 0 的首次未来约定没有保存，当前卡数为零；episode 1 重新收到完整新要求后才创建卡。这不满足本 Goal 的首次持久化验收，不能被 2/2 历史依赖任务通过掩盖。

因此 R2 只澄清 v4 finish_turn 的通用目的：没有既有持久卡不等于已表达；以后需要的新约定／要求应首次保存，即使业务行动暂缓。没有增加订单规则、审核模型、强制逐条写入或 schema 分支。说明经现有 compact catalogue 确认进入真实 JSON-action 请求；单个已有目录投影检查通过，maintenance 的 Ruff/mypy 通过。该检查与前述覆盖重叠，不累加成独立测试总量。

R1 源码映射 5c92005f5e7f2b36c6716dcd8cf5ce1c05091f06fe47141c9f37474c6ff9a773、全部结果与费用封存于 [R1 清单](../data/manifests/contextual-memory-v13-r1-results.json)。R2 从相同原生初态新建独立世界完整复核；这不是新的独立样本，也不是调同一任务直到 5/5 的方法比较。

## R2 结果与最终取舍

R2 的新说明确实进入实际 JSON-action 工具目录，但首次约定仍零写入；Host 明确将“临时、等待确认”理解成不需要保存。原生仍为 4/5，dependent 2/2，Host／维护 7/7 complete。新增 27 次生成、160516 输入＋3804 输出＝164320 generation tokens；九次 embedding 共 1223 tokens，unknown=0、Judge=0、截断=0。

R2 的独立退款同样未执行，故保留原生失败；其回答表达“可进一步申请审批”，没有复现 R1 的“已经升级审批”声明。R2 两张最终卡也没有 R1 的临时短句柄。这些是同一场景的行为差异，不能归因于首次约定提示，更不能择取 R2 的有利片段替代 R1 的最终源码结果。

撤回唯一的 R2 finish 说明后，当前全部 46 份运行文件逐项匹配 R1；相关四份测试文件也匹配已执行检查的散列。最终交付保留 Host 修复回执与正式入口，不保留未起效的提示。R2 修改源码的单文件快照及散列保留在 ignored 制品中，冻结清单能说明它与最终源码的唯一差异。撤回后没有新增模型调用。

## 完整交付及未达标项

工程与有限诊断完成，按负面或不确定效果结项。首次约定持久化 **NOT_MET**；R1 的无回执审批声明、持久正文中的会话短引用仍未解决。两次原生运行均没有自然写入拒绝，新增 repair_guidance 只有窄接线证据，实际节省未确立。没有新增候选、未见场景或 Product 改动。

两轮连续账本为 **56 次生成／345375 generation tokens／2797 embedding tokens**，与 Provider 原始 usage 逐条汇总一致；没有未知用量、Judge 或截断。输入 337502、输出 7873；旧 v12 账本封存且没有重复导入。详见 [最终报告](CONTEXTUAL_USER_MEMORY_V13_RESULTS_20260925.md)、[最终冻结](../data/manifests/contextual-memory-v13-final-freeze.json) 与 [汇总清单](../data/manifests/contextual-memory-v13-results.json)。
