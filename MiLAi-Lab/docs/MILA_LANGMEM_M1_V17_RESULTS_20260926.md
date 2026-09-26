---
version: v17.0
date: 2026-09-26
status: COMPLETE_WITH_M1_LIMITATIONS
decision: PIVOT_REDESIGN_M1_BEFORE_M2
experiment_arm_kind: RESEARCH_PROTOTYPE
method_benefit_claim: false
vllm_settings_changed: false
---

# v17 M1 结果

M1 的单任务状态、真实证据采用、程序重核、同代 state/action adapter 和恢复已实现。修复生成 schema 后，最终 R2 完整执行一个受控机制实例、原 12 例／20 会话及原 arc0／5 集／7 条消息，无协议拒绝或中断。原 vLLM 容器、image、启动参数、环境 hash 和 HostConfig 均未改变。

结论是 **PIVOT：先重新设计判断表达和重核使用，不进入 M2**。机械 adoption 有效不等于判断有用：受控实例在收到新版通知后仍按旧值行动；多数 Basis 是主题标签，原诊断语义为 5/12，未达到 M2 进入条件。没有未见数据或方法收益结论。

## 身份与交付

- [原计划](MILA_LANGMEM_M1_V17_DEVELOPMENT_PLAN_20260926.md)保持原字节；[执行 Goal](MILA_LANGMEM_M1_GOAL_v17.md)、[开发记录](MILA_LANGMEM_M1_V17_DEVELOPMENT_20260926.md)、[复现入口](MILA_LANGMEM_M1_V17_REPRODUCTION_20260926.md)。
- 最终 [M1 lock](../data/locks/milai-m1-v17.lock.json) SHA `d03779620ab8a15c3da7902765b9e477af0207257f809046826e35ee80fceb02`。
- 38 文件源码 mapping `392c14287062a92465f74b31e402ea65099a55cb5136a1c3939b05dd1655b66f`；[最终 freeze](../data/manifests/milai-m1-v17-final-freeze.json) SHA `e263aa177869abf63c1c4faaea55f7a9c00b77960ddf241e304a99f112ffc1df`。
- [机器结果](../data/manifests/milai-m1-v17-results.json)、[成本](../data/manifests/milai-m1-v17-cost-summary.json)、[受控实例](../data/manifests/milai-m1-v17-mechanism-run.json)、[诊断](../data/manifests/milai-m1-v17-diagnostic-run.json)、[MERIT](../data/manifests/milai-m1-v17-merit-run.json)。

默认 B0/B1 分支、原 upstream CRUD/search、Store、checkpoint 和业务 journal 保留。新增的 JSON `decision_delta` 是 opt-in Lab 实验协议；没有 Product API、Schema、权限、Canonical 或 Archive 变更。旧 B1/foundation 锁、v16 结果和账本保留；旧底座复现/回滚身份为 commit `3676c511f4c4087453d5bbf54cea3514e57fd948`。共享文件不能用旧锁冒充原源码。

## 开发与验证

7 项集中零模型测试覆盖实际 Graph/上游 tools 的证据交付与准确版本采用、null/set/clear、相同 set no-op、程序 recheck、tombstone、无关版本、非法 delta 零副作用、原工具参数错误、有序调用、任务隔离、冷恢复与 completed replay。另 1 项原 B1 wire/world/checkpoint parity 通过。受影响 Ruff、14 文件 mypy、默认 core 99 文件 mypy、source/tools 边界、CI YAML 和无 LangMem 的可选测试跳过检查均通过。

R1 暴露 generation schema 过宽：模型生成带多余 `decision` 的 clear，严格 reducer 正确拒绝。修复仅将生成 schema 对齐 null／严格 clear／完整 set；未放宽校验、增加自动重试或修改语义提示。新增 1 项直接验证此差异的测试及相关静态检查通过。两轮各 3 次部署 decoder probe 都通过；R1 的 probe 没有发现自然生成中多余字段的风险，不能将其初始 PASS 解释成完整协议可靠性。

R1 唯一一次 build 验证 sdist 中 38 份源码、wheel 中 28 份 Python runtime 及 M1 lock，未包含私有制品。R2 只改 schema 和对应测试，没有包声明变化，因此未重复 build；R1 包字节不冒充最终 R2 包字节。

收口时补充了一次零模型机械验证：deferred＋gap=null 的冷恢复及新 Observation 投影、切换/返回任务的 notice 与 ack、@2 ack 不重复且 @3 再次触发均通过。证据 `artifacts/langmem-m1-v17/v0-supplement.json` 明确属于 R2 后补核，不冒称冻结前检查。它未修改正式数据或源码。未运行全仓库测试、大规模 benchmark、新 seeds 或额外 Judge。

## R1 失败保留

[失败记录](../data/manifests/milai-m1-v17-r1-failure.json)保存 R1 的来源、完整分母和费用：受控机制按旧 4°C 执行；诊断 d02/d11 第二会话被非法 clear 中断，10/12 例、18/20 会话完成；arc0 在第 2 集中断，仅 1/5 集完成。没有把中断当作普通答错评分，也没有拼接 R1/R2 的有利部分。

R1 全部 38 份源码、lock/freeze、原始回执及数据库留在 ignored artifacts。最终 R2 从新的空 namespace 和原始世界完整开始，原输入、rubric、native checker 均未变。

## 最终 R2 机制与成本指标

Activation 是每次生成处理后 Basis 存在的轮数；同一 Basis 可跨 null 保留。Churn 只计创建/改变的 set 语义 revision；clear、no-op、ack 分开。所有正式状态都是 active，deferred 在真实轨迹中为 0。

| 指标 | 受控机制 | 12 例诊断 | arc0 | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 实际普通生成 | 5 | 30 | 18 | 53 |
| 生成后 Basis / 总生成 | 2/5 | 13/30 | 6/18 | 21/53（39.6%） |
| 生成前 Basis 投影 | 2 | 10 | 6 | 18 |
| set 语义 revisions / 有 Basis 轮次 | 1/2 | 8/13 | 5/6 | 14/21 |
| 相同 set no-op | 1 | 4 | 1 | 6 |
| clear 实际结束 Basis | 1 | 5 | 5 | 11 |
| 合法采用项 / 接受采用项 | 2/2 | 13/13 | 7/7 | 22/22 |
| 其中 memory / Observation | 2/0 | 0/13 | 0/7 | 2/20 |
| 重核 trigger / 投影 / ack | 1/2/0 | 0/0/0 | 0/0/0 | 1/2/0 |
| Decision Context 输入 tokens | 875 | 2168 | 1593 | 4636 |
| decision_delta 字段输出 tokens | 157 | 1027 | 561 | 1745 |
| 独立 State/reflection 生成 | 0 | 0 | 0 | 0 |

22/22 是**采用发生次数**，包括重复 set 中的准确重新交付，不是 22 个不同事实。逐项离线核对了实际 Provider request hash、原 user/ToolMessage 正文、Observation identity、memory revision/content hash 和 FULL search delivery；没有把格式合法等同实际可采用。最终实际 continuation 采用为 0，合法 continuation 的能力仅有零模型证据。

全部请求有 10／32／37 个 delivered 候选出现次数。发生 adoption 的请求中分别有 4／13／13 个当前候选，采用 2／13／7 项；机制与 arc0 表现为子集，诊断 12/12 次 adoption 都采用当时全部候选（多为唯一用户材料）。不能据此声称稳定或有意义的选择性：arc0 最后正确退款时，Host 采用了用户和 get_order Observation，却没有采用实际提供 6595 的 memory。准确引用仍不证明行动参数的完整支持链，memory source_refs 仍为 UNKNOWN_NOT_DECLARED。

Context 与 delta 按本地固定 tokenizer 对原文本片段计数；不把片段相加冒充完整账单中的精确增量。固定 M1 协议另为每次 217 fragment tokens，R2 累计 11501，已在总 input 计费；状态并非只有 Context 一项开销。M1 SQLite 三组为 36864／65536／57344 bytes，合计 159744；未单独测量 M1 CPU/latency，Provider 时间不能解释成 reducer 性能。

## 真实重核链未成功

受控 seed 通过真实上游 manage_memory 写 X@1（4°C），Host 正常 search 后采用该版本。fixture 在第一条公开消息后通过同一工具更新同 UUID 为 X@2（8°C），明确标记 FIXTURE_CONTROLLED_EXTERNAL_UPDATE，不属于模型自主记忆策略。

程序保留 adopted=@1，准确触发一次 revision_changed，并在随后两次普通请求送达原因。Host 第一次保留相同 `holding_temperature` 标签并继续回答 4°C，第二次 clear 后按 4°C 记录。新版正文读取 0，ack 0，recheck 后语义改变 0、保留 1、clear 1。clear 结束了 Basis，但没有被记为成功确认。

这证明 trigger/projection 实际可达，**未证明 Host 完成重新判断**。程序没有自动 rebind、替模型发 search 或拦住旧值业务动作；记录下来的失败正是当前方法限制。原 exposed 两组没有自然 UPDATE/DELETE，也没有自然 recheck，不得借受控变更声称自然链成立。

## 判断、gap 和非干预

按模型请求前冻结的规则人工审查全部 14 个不同语义 set：9 项是 TASK_SUMMARY／主题标签，3 项是最低限度可理解的行动意图，1 项无未来行动意义，1 项偏离任务且不清楚。典型标签包括 holding_temperature、parcel_K17_status、Date Format Preference、agenda preparation、refund_amount；它们缺少需要维持的实际判断或参数。3 项行动意图也不能当作完整支持链，尤其最终退款未采用金额 memory。

只有 2 个非空 gap：arc0 询问 ORD-197802 的 agreed refund amount，确实影响下一退款参数，判为 VALID；d11 询问泛化的 Atlas 技术/业务约束，偏离已知 Nina/load-test log 提醒，判为 UNSUPPORTED_OR_UNCLEAR。其他 12 项 gap=null，不自动判成功或自动 clear。

四个非干预对照中 d01/d04/d10 使用 null；d07 虽正确回答 EVEN，却建立并留下 parity_check，非干预为 3/4。整体 activation 未接近 1，但标签化状态、遗漏实际判断及无用激活使“稀疏有用状态”主张尚未成立。

## 原 12 例语义结果

每例依原 rubric 复核长期记忆边界、后续答案、真实业务调用和必要细节，不用字符串自动评分代替语义判断。基础任务是否通过与 M1 是否应建立状态分别报告。

| 例 | 结果 | 主要证据 |
| --- | --- | --- |
| d01 | PASS | 540；无长期记忆、无 Basis |
| d02 | FAIL | 消息真实且仅一次；未存收据，第二会话搜索为空 |
| d03 | PASS | 保存 ISO 日期偏好，后续格式正确；未证明实际调用 search |
| d04 | FAIL | 最后没有 READY；无长期格式记忆 |
| d05 | FAIL | 存储完整 accessibility/十分钟/demo 前要求，后续却泛称创建并发送议程 |
| d06 | FAIL | 保存日期条件，后续两天均答 kg，漏掉此前 pounds |
| d07 | PASS | EVEN 且无长期记忆；M1 另有无必要 Basis |
| d08 | FAIL | 保存完整待定安排且未预约；后续未保留“明确接受 documents”触发条件 |
| d09 | FAIL | 保存个性化时区规则，后续返回泛化建议，未按 Asia/Shanghai 规则回答 |
| d10 | PASS | 简短确认，无长期记忆、无 Basis |
| d11 | FAIL | Nina/log 提醒已保存，但后续返回通用部署清单；未 contact_person |
| d12 | PASS | 准确保存并搜索 m0 和匹配 connector |

最终 5/12；全部 12/12 例、20/20 会话完成。封存 v16 是 7/12；这是同一 exposed 小样本的开发信号，未进行新的 B1 对照或 matched/unseen 因果检验。不能称 M1 改善质量，也不能把状态输出完整等同任务完成。

## 原 arc0 行为

原生 4/5、dependent 1/2，全部 5 集／7 消息完成。首次 2492 和 503 cents 协议仍未保存（0/2）；后续 ORD-197802 搜索两次均为空，Host 建立金额 gap 并询问用户，未像 v16 那样编造 5000 cents 退款。这是有价值的单条行为差异，无法归因或宣称方法收益。

后来 6595 cents 新协议被保存，最后准确读取并执行该退款；独立全额退款 16100 cents 也成功。最终记忆仍写着 “Do not process yet”，没有随成功退款更新。原 native checker 没有覆盖这一 stale prose，不能把 4/5 当语义正确性全通过。整段仅一次 Host memory insert，没有自然 update/delete；收据、金额 memory 和 adoption 的不同证据含义继续保留。

## 连续费用

| 阶段 | 生成次数 | 生成 tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| R1 decoder | 3 | 2280 | 0 |
| R1 受控机制 | 5 | 6135 | 86 |
| R1 诊断（含 2 次拒绝） | 31 | 27478 | 335 |
| R1 arc0（中断） | 6 | 7538 | 0 |
| R2 decoder | 3 | 2280 | 0 |
| R2 受控机制 | 5 | 6185 | 86 |
| R2 完整诊断 | 30 | 26677 | 343 |
| R2 完整 arc0 | 18 | 23237 | 66 |
| **全部 v17** | **101** | **101810** | **916** |

input 92672、output 9138，known=charged，unknown=0；28 次 embedding，Judge=0。95 次普通 ReAct 生成和 6 次 decoder probe 全部计费，独立 State/reflection 调用为 0。开发代理的平台费用不能从实验账本取得，单独标为 unavailable，未当作零。

R2 全部 53 次／56099 tokens／495 embedding tokens。只取与 v16 同输入的两组 exposed 数据，R2 为 48 次／49914 tokens，而旧 v16 是 55 次／40072 tokens；请求减少但总 tokens 增加约 24.6%，不能声称整体省钱。没有用 request 次数掩盖状态字段及固定协议开销。所有旧 v15/v16 封存费用仍在账本 history，未清零或并入本轮统计冒充新用量。

## 收口判断

工程合同和完整声明运行已交付，确定性 schema 错误已修复。M2 所需的真实成功重核、判断质量、普通任务无明显损害和可接受成本尚未满足，因此本轮以 `COMPLETE_WITH_M1_LIMITATIONS` 结项，决定 PIVOT。下一步若另行开发，应先让 Basis 表达实际判断并使模型在普通调用中使用重核通知；本轮不添加 Attention、硬门禁、强制检索或逐题规则来掩盖结果。

发布沿用授权，由 Luna high 提交和推送所有开发文件；精确远端 commit 与工作区状态记录在最终交付回执。原始 Provider 对话、数据库、模型、私有 DSN、构建输出与运行日志保持 ignored。
