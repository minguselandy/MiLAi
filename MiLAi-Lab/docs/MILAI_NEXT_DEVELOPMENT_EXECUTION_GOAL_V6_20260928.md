---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
plan_sha256: 446e8b401eb558edd76c98dfcda0c0bc9daf1408c7d0d18ba583ce5cb2ea34ee
baseline_main: 05601148c1c060d09c6cd64927a88ad7106aa537
baseline_report: 1abf5c4d6531db831221d537b96c74fab76383ef
baseline_method: ec682a3a8b1ac58b41733b882ed0bad367347fed
research_goal: NOT_ACHIEVED
product: NO_GO
---

# NEXT_DEVELOPMENT v6 执行记录

新的实际线程 Goal 明确要求完整阅读并执行[原 v6 计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v6.0.md)。
Root 已完整阅读 1,497 行。原计划 26,104 bytes、DRAFT/NOT_STARTED 元数据保持，授权来自新的 active Goal。
本次恢复仅适用于 v6，不从旧 ACTIVE 文本启动历史路线，也不把原 v5 已完成状态延用于新任务。

原计划 §1 的 PR #68 Draft/Open 已过时：用户另行授权后，Luna 已将 #52–#68 顺序合入 main。
当前 main 为 `05601148c1c060d09c6cd64927a88ad7106aa537`，完整 tree 与 v5 报告提交 `1abf5c4` 相同。
v5 head 两次 Fast `36393968381`、`36397917433` 均 success，Full `36393968330` skipped；合并 SHA 本身没有单独检查。
原始研究数据、实验失败、所有费用及旧 v27 草稿均保留。原 main 工作树仍在旧 HEAD，七份未跟踪计划未改动。

本轮独立工作树 `/cra/memory/mx_memory/MiLAi-worktrees/next-development-v6`，
分支 `feat/lab-request-context-v6-20260928`，以已核 main 为基底。

## 全部工作包与证明要求

| 要求 | 必须取得的证据 | 当前状态 |
| --- | --- | --- |
| S0 / §7 | 旧 system/candidate、当前/历史、world/DELETE/临时/只读/多事项及费用原样保留，旧分归旧提交 | COMPLETE；159 源文件、14 公开证据、28 个 terminal jobs、131 个生成 ID、86 消息核平 |
| S1 / §8、18、19、23.1–2 | 显式结构化请求对象/renderer/router；无序列化块搬运；old/new wire bytes、capacity/token、audit、原 graph 完全等价；独立源码发布 | COMPLETE；4ffd176/PR70独立发布、远端核对、Fast success；131请求/86审计/22条件26阶段/27窄测通过 |
| S2 / §9、21、23.3 | 明确 Model/Audit 边界、冻结请求组件计量、每项删除依据与 trace 可恢复性，保留语义/ID/scope/业务正文 | ENGINEERING_ACCEPTED_S3B_PENDING；30窄测、131full/compact回放和86审计通过；唯一候选移出wrapper/空容器/模型hash，固定输入-3.80%、记忆组件-9.54%；不硬凑目标 |
| S3a / §10 | S1 机械等价后 2–4 个真实 smoke，所有成本计入 | PASS；4已暴露scripts/13消息/54任务全过；20生成27484tokens、5embedding115tokens已归账 |
| S3b / §10 | 若 S2 改 Model View，完整 12-script/156-obligation 暴露回归；任何退化先定位被删信息，不加 prompt 修分 | REQUIRED_NOT_RUN；12脚本35消息的原合同已准备，待S2源码发布/冻结 |
| S4 / §11–12、17、23.4–5 | 12–16 个独立结构脚本、约 35–50 公开消息；十二任务族、quoted imperative/carrier 边界；显式≥98%、所需持久100%、无跨owner/重复业务/假保存/隐藏rubric失败 | DRAFT_INPUTS_NOT_FROZEN_NOT_RUN；Root草拟12 scripts/40消息与可见义务合同，待S1/S2/S3完成后冻结；不能用旧回归替代 |
| S5 / §13 | 仅 S4 通过后，不改方法/prompt，另一模型家族 6–8 脚本覆盖六类边界 | CONDITIONAL_NOT_RUN；不同量化不算另一家族，开发 subagent 不算实验 Host |
| S6 / §14 | S4 稳定后、最好已有 S5 确认，20–30 sessions 自然积累10–20独立事项，先正常 all，无人为压预算 | CONDITIONAL_NOT_RUN |
| S7 / §15 | 实际阈值/容量触发后 all（可行时）对 ordinary query，命中、质量、全成本核对 | CONDITIONAL_NOT_TRIGGERED |
| S8 / §16 | 实际 query 不足/超容量/可见 scope 错误后，固定共同条件比较 ordinary/working-query/lazy attention | CONDITIONAL_NOT_TRIGGERED；不新增 durable fact copy 或独立 U |
| S9 / §22–25 | 逐项完成审计、真实失败分类/两解释/反思、全成本、复现、Go/Pivot/Stop、Luna 发布与远端核对 | PENDING |

这张表保留完整任务，不把工程整理、最容易通过的几例或最低标准摘录当作整个 Goal。
触发条件按实际证据判定；S4 通过后推进 S5 与 S6，不以“条件项”逃避已经成立的前置条件。
S6 的“最好 S5”不改写为原文不存在的绝对门槛，资源若缺失须如实记录并推进不依赖它的工作。
若 S4 失败，按 §25 定位首断点并做最小通用修复；后续样本暴露状态与所有失败保持。
最终完成仍需 §23 当前/历史/world/临时的消费证据，不能由 source tests 或合并百分比推断。

## S0：现场与证据

[基线冻结](../data/manifests/next-development-v6-s0-baseline-20260928.json)保存实际身份及证据路径/SHA。
v5 R1 仍为 9/10、70/71 显式、59/59 持久；system 诊断当前/历史均0/2；候选诊断均2/2。
最终候选仍为12/12、89/89显式、67/67持久、156/156任务，新内容system仍0/2。
这些旧效果属于 `ec682a3` 等原执行方法，不能因 v6 未来字节等价而改归新提交。

初始无运行中的实验 runner。只读 `/v1/models` 确認既有 Host Qwen3.6-35B-A3B-FP8/maxlen65536，
embedding bge-m3/maxlen8192；实际 recipe embedding dimension1024。
保持 temperature0、max_tokens4096、thinkingfalse、每公开消息最多12生成、真实HTTP并发1。
没有新增 Host/embedding 请求、模型资产下载、部署或服务参数修改。

连续账本沿用原树 `artifacts/ser-v20/budget.json`，起点：
**3125 generation calls /3,971,354 generation tokens /22,221 embedding tokens**。
SHA `98b02945ab195ad94e37061f97c5ba5eb8068ecd87ff47caef9f76f9e51fdd15`，旧 history 与费用不清零。
私密 DSN 仅在真实运行需要时注入环境，绝不写入 Git 或工具输出。

## S1 首个工程断点与竞争解释

Observed：`make_persistent_memory_hook()` 先把 records 串入 system；`MemoryBoundaryView.project()`
在已序列化内容中 count/replace 后移到当前 user；`fit_final_request()` 再找该块以替换 query/attention 候选。
真实工具 catalog 则在 provider 的 project 之后、fit 之前进入 system。
Expected：base、durable、working、history/current 与 action catalog 都有明确输入结构，renderer 在序列化前决定位置；
router 从该结构渲染每个候选并检查最终完整请求，原消息/checkpoint/审计不改。

解释/方案一：这是普通文本拼接的局部耦合，可用共享结构对象与纯 renderer 消除，保留原字节及换行。
解释/方案二：adapter 对 catalog/工具历史的最终序列化与 projection 分属不同阶段，若只局部移走 replace，
仍可能在另一层隐性重建串或丢失真实容量输入，单元测过也不证明跨层等价。
因此先明确 hook→provider→router 契约；不以保留旧字符串搬运的兼容包装冒充完成。
这是已证实的结构问题，没有新的语义失败，不据此改 prompt 或增加 controller。

最小范围由 Sol xhigh 收敛：`methods/memory_boundaries.py`，必要纯结构/render 类型，
`methods/local_state_attention/integration.py` 的 ordinary hook、`providers/langmem_chat.py` 的实际 request 拼装；
只扩展真正受影响的相邻检查。文件数量不是目标，不改业务 runner 合同或旧可选路线行为。
`BOUNDARY_PROTOCOL` 可拆职责但 S1 字节必须原样；system 库默认不变，v6 recipe 显式 current_request。

等价证据覆盖 empty/all/query/attention-prepared、工具续接、UPDATE、DELETE、scope 和 C 历史兼容边界。
详见 [S1工程结果](MILAI_NEXT_DEVELOPMENT_V6_S1_ASSEMBLY_RESULTS_20260928.md)：
Root核平131条实际payload重放、86次操作审计、原checkpoint不变；Sol另补22组/26阶段路由差分及27窄测。
原trace只有有序payload，所称HTTP字节等价是同一锁定HTTPX编码结果，不是未保存的原socket捕获。
BOUNDARY_PROTOCOL四职责常量拼接值保持1232 bytes。S1独立发布前不做S2精简或真实smoke。

用户另行要求GitHub合并后，Luna已将S0 PR69合入main，merge=`07cc364f96d484ad9ff8497adcf2a6f1b486bdb2`，
tree等于S0 `c6dcd1d7`，Fast36400064797 success；Root核对远端SHA、parents/tree、原七份草稿与连续账本。
这次合并只有S0，正在验收的S1另行发布，不把源码工作树混入S0。旧PR51仍未验收、不合入。

S1现已由Luna独立发布`4ffd17664ce9d8a6497e57b199b3a6d764adae86`，draft PR70、Fast36403127754 success。
Root核对精确9文件、远端head/base和S4草稿排除状态。随后完成S2离线profiling与S1-source真实S3a，见
[阶段结果](MILAI_NEXT_DEVELOPMENT_V6_S2_PROFILE_S3A_RESULTS_20260928.md)。
S3a四个完整脚本均terminal且54/54，累计账本更新为3145calls/3998838generation tokens/22336embedding tokens，
SHA`db0b1e4ea95b2c68155e742627cfbbc9fb4c4f9c68d56d5f01aca4f5ea64aa6b`；无语义或基础设施重试。
这不是完整S3b或新S4证据。S2实现放行于S3a全部终止之后，仍由Sol唯一写入相关源码/测试/新config。
S2的Model/Audit字段边界、默认full、未知额外字段保留、tool metadata结构化及compact实际容量均须验证；
不通过删除更多语义去达到10%–20%的工程目标。

## 职责、冻结和验收纪律

Root：计划/报告/合成 fixtures/rubric、协议与输入冻结、所有真实调用、语义评分、分析、完整成本与验收。
Sol xhigh：唯一源码/配置/runner/adapter/必要检查负责人；每文件一个写入人。
Luna high：必要公开资源下载（只在实际阶段需要时）与已授权 Git commit/push；不承担语义效果裁判。
Astra xhigh：仅具体困难冲突，提供证据、最小复现、已试方案与明确问题；不是常驻审计。
优先复用模型匹配的现有代理；不静默降低模型/推理等级。

真实评估前冻结源码、输入字节、模型/工具、评分、组顺序、namespace/Store/checkpoint/world 隔离；
先发布，再在该提交 prepare/freeze，避免 v5 的 Git SHA 身份前置故障。
运行时不读取 gold/rubric，不用样本 ID、标准答案或业务值作路径判断。
完整核对输入→实际HTTP→工具/world→持久化→后续交付→实际答复/动作；进程退出不等于语义通过。

每次失败记录 Observed、Expected、实际因果链、First broken link、至少两解释、通用修复、混杂、最小下一实验、Continue/Pivot/Kill；
每阶段回答长期计划十项 Reflection。保留首次失败、重试、空提取、观察与所有费用，不能拼接最佳轨迹。
报告区分 input/output、embedding、Store逻辑calls/bytes、business/control、process/HTTP时间、unknown；
fixed-request 输入差与真实轨迹总费用分开，开发代理 tokens 与实验账本分开。

纯文档/清单仅检查 JSON/链接/哈希，不运行模型或整套测试；已有通过检查不为发布重复。
既有 vLLM 设置不改；优先复用公开 LangGraph/LangMem API、现有 runner 和薄适配。
Lab-only，Product NO_GO；不自动恢复旧 M1/ODR/第二份 State facts 或过期 v27 方案。
原 plans/protocols/failures/锁不重写，新阶段各自记录真实身份。

S2源码现已由Sol完成、Root核平并验收，详见[实现回执](../data/manifests/next-development-v6-s2-implementation-checks-20260928.json)。
30窄测、131full默认等价与131compact预测匹配、86审计及原checkpoint保持；未做新的真实调用。
库默认system/full不变；S3b尚未运行，不能宣布compact语义通过。下一步Luna发布已验收源码与阶段结果，
然后Root在确切发布SHA上prepare/freeze并串行回归；S4草稿仍不发布、不执行。
