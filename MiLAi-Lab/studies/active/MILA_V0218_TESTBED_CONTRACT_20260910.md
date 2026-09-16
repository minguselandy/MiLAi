---
version: "T5.READY.E0.E1.E2.E5.COMPLETE"
status: WHOLE_GOAL_COMPLETE_KEEP_SIMPLE_ENGINEERING_GAIN_ONLY
profile: MILAI_ADAPTED_BEHAVIORAL_TESTBED
active_model_request_allocation: 0
model_requests_executed: 1340
raw_tokens_executed: 3353114
judge_requests_executed: 0
---

最新摘要（2026-09-11）：[E5 决策](MILA_V0218_INNOVATION_DECISION_20260911.md)完成全 Goal 验收。
T0–T5/E0/E1/E2/E5 COMPLETE；合格机制候选 0，E3/E4 NOT_TRIGGERED，全部 12D、未打开 C=0。
判定 KEEP_SIMPLE_NO_CANDIDATE + ENGINEERING_GAIN_ONLY；测试床贡献候选仍须外部复核。
[T5](MILA_V0218_T5_REVIEW_20260911.md)限定适配 12 原 lineage / 9 coarse family / 49 分支；
[E0](MILA_V0218_E0_V4_20260911.md)完整标准和单列 probes，统一 S*=N1；
[E1](MILA_V0218_E1_DISCOVERY_20260911.md)两候选/两次冷运行；
[E2](MILA_V0218_E2_RESULTS_20260911.md)32 episodes/五臂同信息/30 真实冷双呈现完成审计。
C2/R1 逐对相同，日程工程胜例保留，未决和新闻更新失败不删除，不宣称独立新机制。
全部 14 模型批次 1340 requests / 3353114 raw，pending/unknown/violations=0，raw cap=null。
自有服务已停、卷与失败证据保留，无活动分配；1258 tests / 1 optional skip、Lab 门通过。
下文较早未完成描述保留为历史建设账；以本摘要、E5 与 Git 外终结审计为最新状态。

# V0218 执行合同与建设账本

执行范围是 [Goal v0.2](MILA_V0218_行为真值测试床建设_GOAL_20260910.md) 的完整 T0–T5/E0–E5，
不是 V0217 的准入续写。[资源/来源范围](../../configs/v0218-testbed-scope.json)先于新模型结果冻结。
本文件逐阶段追加实际证据；无完成记录的阶段保持未完成，不用计划代替执行。

## 路线与来源

采用显式本地适配的权威 SQLite 对象世界：工具写入会真正改变本批隔离数据库，
不是返回假成功的邮件/Notion stub，也不是 ClawMark 原生服务复现。
Product 只承担公开持久记忆接口；测试世界/事件/checker 均留在 Lab。
世界状态、业务操作日志和离线 checker 分开；checker 不能以模型宣告判完成。

首两个纵切来源为 V0217 固定 ClawMark 的 executive_assistant/task2、insurance/task3。
原始 task.py/hash、必要资产下载位置统一在 Git 外；本地适配删减如下：

- 日程：保留候选/时段/房间/远程模式、外生可用性变化及完整日程约束；
  不复现证件图片、音频诈骗判断、报销、真实邮件泄密或 Google/Notion 服务。
- 理赔：保留案件身份、有效版本、来源优先级、延迟与保单条件、未决核验和可逆裁定；
  图像证据改为明确发布的结构化业务记录，不声称验证原始截图识别能力，不实际支付。
- A/B 及 Stable/Superseded 等配对是新增适配，不是原生 benchmark 的完整故事/评分。
  旧值是 A 时有效记录，不能把仅有投保人自述当作已证实真相。

许可继承来源的 CC BY-NC 4.0 标识，保留出处、差异与本地文件 hash；没有商业授权或原生成绩声明。
用户另行要求下载 benchmark 并提供 hf.env；凭据只在下载进程内使用，其文件权限由 0644 收紧为 0600，
不输出值、不进入 Git/日志。固定 WMA 全量数据和 ClawMark 资产下载本身不使 C 内容进入设计者上下文。

## 日程日期歧义：先冻结解释

原脚本 stage2 把 2026-03-24 称作 Monday，且同时出现 tomorrow/Wednesday/2026-03-26；
实际 2026-03-24 是 Tuesday，03-25 是 Wednesday，03-26 是 Thursday。
本适配明确以 ISO 日期为准：C03 的 03-25、C04 的 03-26 分开；不保留相矛盾的星期与 tomorrow 指令。
这是公开 task profile 修订，不是在模型答错后改 checker。
缺开始/结束时间不可通过；多个合法时段/计划可以通过，禁止把唯一示例 trace 当 gold。

## 世界、观察与评价规则

机械动作层只处理授权 scope、对象许可、请求类型、事务/CAS、幂等及实际状态变化，
不替模型挑选正确业务方案。独立 checker 从快照和公开业务约束判完整状态；
故意变异快照/错误业务行动必须能让 checker 失败。
操作 `read` 可取当时合法的 task/policy/current/history/records；未来事件与私有标签不在世界库。
业务动作可重复修订；错版本和跨 scope 动作拒绝，不默默换到 head。

SUSPEND 只在公开必要事实未决时有效，并需真正记录待核验事项；充分证据下无限暂停不能过门。
KEEP 不要求无意义重写；更新后沿用旧方案不能靠“我已修正”获得通过。
RECOVER 保留早期错误账本，要求后续真实状态修复；无自然错误时条件率 N/A。
预定事件/公开业务反馈在 A/Note 产生前固定，不根据模型笔记制造反证。

单测预期由开发者依据外部来源先编写；本轮为开发自审，不能宣称独立人工复核。
每 root 校准包含正例/多解、缺字段/空值/错型/未执行、对象/时区/版本、否定/引用/混合值、
未决与充分证据、幂等/reset/clone、无关插入/重命名/顺序变化、错误实现变异、未来/gold/scope 泄漏。
原生局部 checker 结果独立保存，适配 checker 不标 native rubric。

## Pool 与阶段约束

目标 12 个外部 lineage、≥3 family；重复 seed/实体/变体不算新 root。先做上述两个纵切，
其余按冻结候选顺序和非结果资格审查；不得按 NO_WRITE、答错或不显著换题。
默认 8D/4C 只在能维持 C 盲隔离时成立。人工适配中读过正文的 root 必须归 D；
未取得真正未打开 lineage 则留确认缺口，不假称 C。旧保护池不访问。
建设门需完整覆盖/可重放 checker、公开持久与至少两个独立 lineage 的真实自写 Note 双呈现链。
没有 G-TESTBED 不开发候选；过门后继续 E0–E5，不以测试床单测通过结束整个 Goal。

## T2 前已发现的接线问题

当前仓库 `uv run milai-lab-verify-product --lock product.lock.json` 报 tree/source-manifest 和
若干 public-interface digest mismatch。保留该诊断，不使用当前工作树作为实验运行版本。
T2 已核验不可变 Runtime 0.1.4/MCP 0.1.15/Client 0.1.3 交付物、安装 wheel 源文件和公开目录，
独立本批 lock 验证通过；
不静默改全局 lock、不绕过校验、不重启或修改现有共享服务。

## T3 前进度与预分配（保留原记录，最新进度见下）

T0 来源/路线/歧义及资源范围已登记；ClawMark、WMA 代码、Supersede 已下载并核对 Git blob，
WMA 固定 HF 全量快照仍在下载，保留缓存并将下载并发单独修订为 12。

T1 两个纵切的 6 个脚本世界重放完成：Stable 旧状态合法，Superseded/Unresolved 旧状态失败，
真实写入修复后通过。证据在 Git 外 `evidence/v0218/20260910/t1-replay-v1`。
这些是脚本接线测试，不计 Agent 的 KEEP/REVISE/RECOVER。
T2 `t2-note-preflight-v1` 实际公开 Note 写入、分页冷读和跨 scope 拒绝已通过，
三个不同进程退出均确认，隔离 API/PG 已停止，卷保留；harness seed=1、Agent write=0、模型=0。

T3 首批在任何模型结果前分配：2 个兼容请求 + 2 个共享 A + 8 个 Stable/Superseded × N0/N1 B，
每 episode 最多 16 次生成，合计最多 162 次；4096 输出容量、60 秒单请求、900 秒 episode、
9600 秒整批、生成并行 1、累计 raw token cap=null，未知 usage/提交结果停止且不自动重试。
冻结源文件、公开 schema/system、数据/hash、模型配置/tokenizer/template；每 episode 验证。
NO_WRITE 保留，N1 仅逐字恢复实际 A 自写公开 Note；N0 保留同一 A 业务记录/普通来源历史。
最后一个动作机会预留交付，之前至少两次动作机会可修复；不会强制制造错误或替模型修复。
两条真实链尚待执行审计；12 lineage/≥3 family 覆盖未齐，G-TESTBED 未通过，E1 未进入。
整个 Goal 保持 active，后续仍需完整 T4–T5/E0–E5。

### T3 共同接线修订（业务任务结果前）

`t3-note-chain-v1` 的两个兼容请求消耗 145 raw token，usage 全结清。
read/current 成功；put_record 返回缺 expected_version/data，兼容断言失败，业务 episode=0。
原协议仅将 schema 给约束解码器，未在模型可见输入里显式展示完整动作格式；
共同修订为初始输入增加 action_schema，离线测试同时覆盖 N0/N1 的错误反馈、来源随下一请求呈现，
不将离线模拟称为真实呈现或宣称已证明模型遵从。
`t3-note-chain-v2` 不追加兼容生成（Goal 的两次已用完），仍是原 2A+8B、最多 160 次真实任务生成。
首个实际任务及其协议错误均计入 T3 总流程，不能包装为额外免费 smoke；
v1 的 2 次和 v2 实际数汇总，不重复/隐去失败，不按单臂或模型结果改任务/checker。

v2 实际 80 requests / 165,019 raw token，5 个已启动 episode；反复缺 expected_version/data，
最后一个输出无法解析而停止，第二 lineage 未启动。3 次 B 自写 Note 已公开提交，
但共享 A 为 NO_WRITE、业务记录始终未成功创建，不能算合格 A→B 记忆链。
用量无 pending/violation，API/PG 已清理、卷保留。增加可见 schema 并未解决问题。

v3 再冻结一般协议修复：所有动作统一使用必需的 action + arguments_json，
后者是 JSON 字符串封装的具名参数；保留原机械工具/作用域/业务规则，
不把语义正确值或案例专属字段列入生成约束，不换 root、不强制写 Note。
编码、类型/原文保留、未知字段拒绝以及 N0/N1 Host 回归在零模型测试中验证。
本次技术修复重放仍限定原 2A+8B、最多 160 requests、原时限；额外兼容生成=0。
此前 82 requests / 165,164 raw token 全计入建设总成本，本批后上界为 242 requests，
这是技术失败后的显式有界共同重放，不是从旧失败中挑选成功基线；仍不声称协议效果已验证。

## T3 实际审计与 T4 扩展进度

v3 已跑完 2A+8B、72 requests/125,609 raw；累计所有尝试 154/290,773，全部结清。
详见 [T3 初步审计](MILA_V0218_T3_PRELIMINARY_20260910.md)。日程 A 自写 Note 且当时事实正确，
两个 N1 B 均有公开精确冷读与实际请求双呈现；理赔 A 金额错误且 NO_WRITE，保留而不换题。
只有 1 个合格独立自写链，不满足 G；没有进入 E0/E1，也没有新增候选机制。

T4 按既定第 3 个来源 research_assistant/task3 增加 release_control 纵切（开发暴露）。
source SHA-256=`3a40b697841e5fe38f43bd577718cbbce469efc126405741306cb31552b7f509`，
contract SHA-256=`f60dfe036028800dbaf10274ab1c8563cfe9c17c2bb0e3118b69ca060853d509`。
保留 native v2.1/v3.0 合同/部署差异和 3/31→3/28 截止关系；增加显式外生修复到 v3.0 的 B，
本地发布授权/审查时间/内部分发计划取代 Notion、报告/邮件送达与照片识别；
不声称实际软件部署、外部邮箱防泄漏或学生监督全题通过。该原 task 只计 1 root。
22 项新增单测通过；Git 外 `expansion-v1` 和 `t4-third-replay-v1` 完成
Stable/Superseded/Unresolved/Irrelevant 的真实 SQLite 脚本重放，全部符合独立预期；模型=0。
发布适用范围的无关通知是非因果控制，不计 Helpful 世界或新 root。

当前已建 3/12 lineage、3 family；仍缺其余来源与完整校准/Helpful/适用范围覆盖、第二条真实链，
不能因 family 达标就过 G。第 4 个既定来源 investment_analyst/task1 正文已审，为 D，尚未实现。
完整 Lab 回归 876 passed/1 optional SDK skip，Ruff 通过；下一次交接还要复核其余 gates。
WMA 全量数据下载继续，详情见 [下载账本](MILA_V0218_BENCHMARK_ACQUISITION_20260910.md)。

### T4 第四来源的零模型校准

investment_analyst/task1 的 financial_basis 纵切已实现：4 个分离口径的指标行和
1 个 guidance−consensus 派生比较行，共同构成一个 lineage，不把 5 行拆成 5 个 root。
原 13.4B/14B、89B 与 90.68B 的近似来源数字在适配合同里明确作为精确公开数据；
新外生 B 共识 88.5B 是显式适配事件，不声称属于原生任务历史或现实市场更新。
更新后 gap=0.5B；单位 BUSD/MUSD、符号、reported/adjusted/guidance/consensus、
期间与版本均分开核验。省略 PDF/音频/XLSX 提取、LP/CRE/FDIC 叙述与全套 peer 判断，
不运行交易/头寸修改，也不声称通过其原生 guardrail。

开发者首版两个正例误写 gap=1.5B，被独立 checker 拒绝；只修正 literal fixture 为 0.5B，
不改公开事实/判据；失败记录在 `t4-financial-fixture-calibration-failure-v1.json`，模型=0。
22 个新增金融单测通过；`expansion-v2` 封存第 3/4 来源，原第 3 合同 hash 不变。
第 4 source hash=`8bcef124b285a56ac117aac54fae3fd0e48da6419d47240e833c6964636f3135`，
contract hash=`85fd0f99690f7c5f2a36a9a39a7ffd732178475325416a87c2b017695fee8394`。
`t4-fourth-replay-v1` 的 Stable/Superseded/Unresolved/Irrelevant 实际 SQLite 脚本重放通过，
执行前复制 checker/world/prepare/replay 源文件。第三次旧 replay 的 checker 后续从未改动的
源码部分精确重建，完整 SHA-256 与原运行记录一致；如实注明不是运行前复制，原结果不改。

现在已建 4/12 个来源纵切、4 family；第 3/4 来源模型仍为 0，未按 NO_WRITE 替换前两题。
未有新的模型分配。下一步包括完整 checker 变异校准、按既定顺序补余下 8 来源、
补充世界与合法自写链，再判断 G；不能仅凭这 4 个纵切或单测数量进入候选开发。

### T4 第二个有界建设批（2026-09-11，结果前登记）

8 个受控 checker 实现变异均被独立正/负 fixture 杀死，另有金融对象重命名不变性测试，
共 9 passed；JUnit 在 `t1-checker-mutants-v1.xml`。不将 8 个选定变异冒充穷尽正确性证明。

原先冻结顺序的第 3/4 个来源完成零模型校准后，分配一个 T4 建设批
`t4-note-chain-v1`：2 个新 A、8 个 Stable/Superseded × N0/N1 B，最多 160 次生成；
每 episode 16，60 秒请求、900 秒 episode、9600 秒批、4096 输出、生成串行、raw cap=null。
兼容生成仍为 0，引用 v3 已实际工作的共同 Host/Provider/Note 传输 hash，不重计该批旧成本。
当前累计实耗仍 154/290,773，本批后累计生成上界 314。原两题（包括 NO_WRITE/金额错误）保留，
不是按成功条件替换题目；本批所有 A/分支同样保留 NO_WRITE、语义错误和资源截断。
不打开 C、不生成机制候选。即使新增真实链出现，也仍缺 12-root/完整补充世界覆盖，不能直接过 G。

该批现已完成 56/93,307；总 210 requests/384,080 raw 全结清，服务已清理。
两个批合计两个来源确有自写 Note/公开冷读/实际双呈现，但金融 Note 混有错误的完成状态推断，
不能将整个 Note/任务判为正确。详细结果、非盲语义复核和相同请求字节的输出差异见
[T4 进度报告](MILA_V0218_T4_PROGRESS_20260911.md)。当前无新模型分配，G 仍未通过。
第五来源 journalist/task5 的原 DB/事件 profile 已准备，checker 待实现，尚不计 ready。

后续零模型更新：第五来源 checker、22 项专项测试和四分支真实世界重放已完成；
另在其首次模型/Note 之前冻结 Helpful v2 显示变体，8 项专项校准及五分支重放通过。
完整历史对两臂正常开放，不删除既有业务成果；详见 T4 进度的后续校准节。
当前 5/12 来源完成世界校准，4 个来源有模型尝试；Helpful 仅一来源、尚未模型运行。

继续按原序完成第六至第八来源后，当前为 **8/12 来源完成世界校准、4 个模型尝试来源**，
Helpful 跨两个来源（同属 journalism 上层聚类），仍无 Helpful 模型实验。
新合同/原始资产核对、适配假设、测试与重放见 T4 进度后续各节；本次扩建模型新增 0。
第九源正文已读但未构建；所有新增均为 exposed development，不宣称独立 C 确认。
