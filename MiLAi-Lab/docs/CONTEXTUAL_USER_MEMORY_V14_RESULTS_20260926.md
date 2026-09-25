---
version: v14.0
date: 2026-09-26
status: IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES
baseline_commit: 488a4291925c607f6d0dc313a7dcbaf1906a6fad
final_source_mapping_sha256: 944cda954858d7181624fc25c72ada717d3bd973e5231b29ecab85751e7f66ab
scope: MiLAi-Lab
---

# v14 交付：结构保障已实现，语义基线未达标

**本轮完成 A–D 开发、V0 窄检查、分阶段 V1 和最终源码 V2；结论为 IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES。** 首次未来价值判断、实际回答的依据以及业务完成后的记忆更新仍有反例，不能恢复 State–Attention 比较。按 [Goal §6](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v14.0_20260926.md) 如实交付未通过结果，不以结构检查或 native 分数宣称语义目标达成。

最终源码从原始世界、空记忆完整运行已暴露的 arc0：**native 4/5、dependent 1/2、Host／维护 7/7 complete**。首次两个独立退款约定均未在首次会话边界保留，后续一次依赖任务缺少金额；另一笔退款成功后，当前卡仍写“尚未处理”。V3 因门槛不满足而 **NOT_RUN**，没有生成、读取或替换新题。

## 1. 已交付实现及其保证范围

| 包 | 实现 | 证据与限制 |
| --- | --- | --- |
| A | 既有 maintenance.pending/frontier 中提供直接观察候选、未来用途 dispositions、真实 write_facts；task 写入不会自动移除跨会话处置候选 | 未处置或没有真实持久结果的跨轮声明不能被 processed 吞没。Host 仍会明确选错 task_local／none；来源关联不证明全部含义都已吸收 |
| B | 复用 raw/reconciled journal，投影真实工具、状态和已交付回执；finish 与 HostResult 分别保存完成引用、pending_actions、原始 answer | 自定义 artifact 的正式 MERIT 回执现可核对；可见的合法既往成功回执可引用，错误身份拒绝。结构合法不证明自由文本真实 |
| C | Host 在提交前检查实际已发布 token；literal_uses 要求有效原始来源字符支持；全量 REVISE 和 patch 新片段使用同一检查 | 支持真实同名字面值及区分大小写／中文边界。局部 patch 不改未写片段，旧污染单独报告；不迁移 v13 旧卡 |
| D | 同轮 schema、文字目录及 dispatcher 使用相同能力；实测后删除重复规则；独立 v14 notes／maintenance-v5／write-v14 | 实际解码器支持新字段。字面例外字段后置解决有序语法的可达性问题；不认领总体成本或缓存收益 |

另删除 COMMON_PROMPT 将所有临时计划指定为 task State 的冲突旧句，保留按未来用途决定持久性的合同。这消除了文字矛盾，但 R5 并未修好未来提醒的语义分类。没有强制全存、gold persistence_required、答案改写、第二份语义账本或运行时审核 Agent。

仅 Lab 改动；Product Schema/API/权限/Canonical 不变，无新数据库、包移动或跨 bundle 私有依赖。v13 源码身份、失败与封存费用保持原样。一个 Sol xhigh 负责核心；root 冻结和运行，真实请求并发 1；Astra xhigh 只做一次限定的难点诊断，Luna high 负责已授权发布。

## 2. 冻结身份与 V0

[最终冻结](../data/manifests/contextual-memory-v14-final-freeze.json)包含 47 份运行文件，映射为 `944cda954858d7181624fc25c72ada717d3bd973e5231b29ecab85751e7f66ab`。最终配置字节 SHA 为 `a5d0c9fc36d23d1db28c7531008fbe808cbc21dbda6be8ed9694f628a7a4d69a`；R5 与 V2 使用相同设置和源码。运行器历史状态名 DEVELOPMENT_COMPLETE_READY_FOR_BENCHMARK_SELECTION 仅表示实现冻结，不表示 semantic readiness。

Host 为 Qwen3.6-35B-A3B-FP8，temperature=0、thinking=false、JSON action、每消息容量 12、输出 4096、上下文 65536；embedding 为 bge-m3／1024 维。vLLM 0.27.1、xgrammar 0.2.3；服务未变更，prefix caching=false。模型／tokenizer 与原始 arc/world 身份来自先前官方准备，并在最终正式入口重新核对；没有为相同文件重复散列全部模型权重。

V0 的受影响六模块初次检查 88 passed，后续 D/C 检查 70 passed；二者重叠，不能相加。错误反馈、字段顺序和 task 候选修复分别有针对性检查；自定义 artifact 回执修复为 4 项窄检查。最终补齐 Host 层 full REVISE／delta patch 新引用拒绝不改原卡、合法 patch 保留旧文并报告 inherited_prose_issue 的 **3 项检查**，未改变运行源码。受影响 Ruff／mypy／diff 检查通过；仅删除冲突句时没有重复跑测试。

[合同检查](../data/manifests/contextual-memory-v14-contract-checks.json)及[有序语法检查](../data/manifests/contextual-memory-v14-literal-order-check.json)保存部署版本的 11 个正反探针。字面声明位于修复字段之后的同一探针由拒绝变为接受；不是只用 JSON Schema 验证代替实际解码。最终补充检查见[清单](../data/manifests/contextual-memory-v14-final-checks.json)。未运行全套测试、构建或边界套件。

## 3. V1：冻结诊断与分阶段反例

[输入](MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_INPUTS_20260926.md)与[独立 rubric](MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_RUBRIC_20260926.md)在首轮前冻结：12 个虚构实例、20 个会话，不算 MERIT。输入 SHA `a6852f07b4b1801e0426cb9ca930c518b3182ac2d5b9f2754f9109e98bf862bc`；rubric SHA `62ab23a2a15f2ef3b81ecb51a715a19e379d24581b90ade2e9b8c12968a0ebcc`。所有轮次保持原字节，runner 不读取 rubric，不向 Host 注入分类或判分标签。

| 实例 | 维度 | 最近实际观察及来源轮次 |
| --- | --- | --- |
| d01 | now / task_local | R1：计算正确、关闭后零卡／来源 |
| d02 | now / cross_turn | R4：首次回执保存并可跨会话使用；实际回答却把消息指令说成包裹仍在指定位置，G3 失败 |
| d03 | now / durable | R3：日期格式要求首次保存，下一会话使用 |
| d04 | later / task_local | R4：零过度保留；回答未按要求以 READY 结尾，任务失败 |
| d05 | later / cross_turn | R1：首次保存未来议程要求，下一会话和独立进程可读；未提前发送 |
| d06 | later / durable | R3：未来生效的单位规则保留并按日期使用 |
| d07 | conditional / task_local | R3：条件答题正确且无持久保留 |
| d08 | conditional / cross_turn | R3：等待条件与取件要求首次保留，未提前执行；一次协议引用拒绝后改写 |
| d09 | conditional / durable | R3：可复用时区条件规则保存并使用 |
| d10 | none 控制 | R3：遵守明确不保存，关闭后零卡／来源 |
| d11 | 临时格式＋未来约定 | R5：本轮一个项目符号正确，未来提醒仍写为 task，关闭后零卡／来源，后续漏答，G1 失败 |
| d12 | 字面碰撞控制 | R3：首次正确保留真实 m0 型号及连接器关系，新会话／独立进程可读；此前 R1/R2 失败和 R3 一次拒绝保留 |

表格是逐例开发记录，**不是最终源码上的一套全通过结果**。R1—R5 映射分别以 `2c48ef67`、`25ab9a6f`、`1532ef2e`、`e624311f`、`944cda95` 开头，完整身份见各轮 freeze。最终源码只定点复核 d11 及运行完整 V2；已知反例仍在，没有为拼出成功率重新跑整套。

d12 的失败链促成两项通用修复：保留可行动错误及字面出处路径；把可选 literal_uses 后置，使有序解码能在普通字段之后表达例外。R3 成功不是零拒绝成功，也不能证明所有混合字面／指代语境正确。d11 的显式 task_local 误判在 task 写入候选修复和冲突句删除之后仍存在；没有发现输入漏发、存储或恢复断点。

分轮结果：[R1](../data/manifests/contextual-memory-v14-v1-r1-results.json)、[R2](../data/manifests/contextual-memory-v14-v1-r2-results.json)、[R3 字面](../data/manifests/contextual-memory-v14-v1-r3-literal-results.json)、[R3 其余](../data/manifests/contextual-memory-v14-v1-r3-remaining-results.json)、[R4](../data/manifests/contextual-memory-v14-v1-r4-results.json)、[R5](../data/manifests/contextual-memory-v14-v1-r5-results.json)。

## 4. V2：最终源码完整原生回归

MERIT 固定提交 `293933d96b1d1849e1f20d1bb324def5de9ed33f`，base_seed=0、hard、五集七条原始消息；原始 arc SHA `32e50fc25c1ce473eccb5c0653e3867072d792c9aed80148236f9b0baff5d12f`，世界 SHA `221f4be1976ff8bc44ddc97b121dea6e15c22d79eff15dfe551a914342569b29`。未改原生工具、checker、消息或边界。它已暴露，只能作开发回归。

| episode | native | 实际语义结果 |
| --- | --- | --- |
| 0 首次约定 | PASS | 发确认消息后把来源选为 none；关闭后零卡／来源 |
| 1 更正与另一首次约定 | PASS | 两条消息都选 none，两个金额均未保存 |
| 2 依赖执行＋另一金额更新 | FAIL | 找不到先前金额，改为询问客户；第二条消息才创建另一订单的新金额卡 |
| 3 独立退款 | PASS | 确有成功退款回执，回答有依据；未查询政策，不能据此声称解决 v13 的政策／工具歧义 |
| 4 依赖执行 | PASS | 正确使用已存的新金额并退款；未修订当前卡，仍显示尚未处理 |

两项不同订单的首次保留为 **0/2**；若另数完整轨迹中四次约定／金额更新的边界，保存为 **1/4**。后者不是“首次成功”。共一次 CREATE、零 REVISE，最终一张 CURRENT 卡状态过时。episode 4 的 work_note 声称已经更新，但程序 committed_changes 为空；工作笔记不是提交证据。

七次实际最终回答中未发现无回执的业务完成声明，结构执行引用均有效。五次 finish 拒绝（四次未处置候选、一次重复 disposition）经后续合法处置结束；零业务工具错误、零写入拒绝、零截断。这证明候选机制能要求显式理由，却没有阻止错误地将未来事项选为 none。

独立进程读回同一张过时卡，并重放 episode 4 的已完成 turn：答案相同，原 journal 两个 succeeded 动作，无新业务／Provider／embedding 调用，状态文件哈希不变。恢复保障通过不抵消记忆语义错误。[V2 紧凑结果](../data/manifests/contextual-memory-v14-v2-results.json)保存逐集指标、归因及制品哈希。

## 5. Readiness 与失败分类

| Gate | 结论 | 有限证据 |
| --- | --- | --- |
| G1 首次保留 | **FAIL** | d11 最终源码仍丢失；V2 两项首次约定均未保留，后续真实执行后也未更新当前卡 |
| G2 不过度保留 | 已运行控制中通过 | task-only／none 控制零持久化；不同轮次证据，不宣称最终源码整套通过 |
| G3 执行依据 | **OPEN FAILURE** | 结构及恢复检查通过，V2 七个答案有依据；V1 d02 的无依据仓储状态仍未关闭 |
| G4 自包含与字面值 | 有限检查通过 | 实际 CREATE 字面碰撞可用、V2 新卡无协议指代；full REVISE／patch 由 V0 覆盖。正文可读不等于当前状态正确 |
| 实际任务完成 | **FAIL** | d04 格式任务未完成；V2 一项依赖任务失败 |

主要分类为 MEMORY_MISS（首次 future_use 误判）、MEMORY_MISUSE（过时 CURRENT 状态、无提交却声称记忆更新）、ACTION_GROUNDING_ERROR（消息指令冒充外部状态）。d04 单列 TASK_COMPLETION_ERROR，避免把普通答题失败伪称存储问题。V2 没有证据支持 BUSINESS_TOOL_ERROR 或 SCORING_MISMATCH，原生分数原样保留。

诊断显示问题已经从可定位的接线／字段可达性错误，收敛到同一 Host 在已交付合同下的语义选择和自由表达错误。本文不把更多重复提示、强制保存、扩大模型或换题作为“完成”手段，也不从一个成功例外推出稳定可靠。没有符合条件的 State–Attention 研究基线；后续方法变更须单独提出可证伪的机制假设。

## 6. 全部费用与局部开销

| 阶段 | 生成请求 | 输入 tokens | 输出 tokens | 合计 | embedding tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| V1 R1 三例 | 7 | 21101 | 1542 | 22643 | 125 |
| V1 R2 字面失败 | 3 | 9509 | 594 | 10103 | 0 |
| V1 R3 字面复核 | 4 | 12798 | 799 | 13597 | 92 |
| V1 R3 其余九例 | 25 | 77760 | 5949 | 83709 | 775 |
| V1 R4 三例复核 | 10 | 33321 | 2520 | 35841 | 278 |
| V1 R5 冲突句复核 | 4 | 11840 | 963 | 12803 | 26 |
| V2 完整 arc0 | 27 | 132706 | 5696 | 138402 | 244 |
| **v14 全阶段** | **80** | **299035** | **18063** | **317098** | **1540** |

共 27 次 embedding 请求；unknown=0、Judge=0、HTTP 错误=0、生成截断=0。R1/R2 的中断及所有修复均计入，累计上限保持 null。v13 的 56 次／345375／2797 独立封存，不清零、不混算。开发代理费用另列，当前没有可归入此实验的代理计费明细。

D 的同 schema、同状态、同能力零模型测量：普通 system 2493→2165、总输入 2818→2490；强制结束 system 2492→684、总输入 2860→1052。后续语义修复改变了说明，最终样例普通 system 为 2244、结束为 763；不能继续把中间最小值当最终成本。

V2 实际 27 请求中，system 本地累计 71051 tokens，frontier 消息 13994；execution_facts 序列化子集 4104 已包含在 frontier，不能重复相加。七次被接受的 dispositions 序列化估计为 440，不等同所有生成输出。全部 Provider 调用墙钟合计约 170.622 秒（V2 约 59.154 秒），不是实验总历时或延迟改善。缓存计费字段 unavailable，未估算收益。[完整费用清单](../data/manifests/contextual-memory-v14-cost-summary.json)逐条从保留的 Provider usage 汇总并与连续账本核对。

## 7. 交付与复现

源码、独立模板、输入／rubric、exposure 规则、分轮冻结、失败结果及费用均有公开紧凑清单；原始语料、请求、世界、数据库、模型和源码证据快照保持 ignored。最小入口见[复现说明](CONTEXTUAL_USER_MEMORY_V14_REPRODUCE.md)。没有消费 seeds 3/4，也未开启新模型或 State／Attention 对比。

`23132fb` 和 `972c833` 为已发布开发快照；本次最终交付前回退基点为 `972c8339fd8ee19ea6bb40a21f9f502a4008596b`。最终 Git 提交及远端核对由 Luna high 执行，提交 SHA 在交付消息中报告。语义不达标不因发布而变更。
