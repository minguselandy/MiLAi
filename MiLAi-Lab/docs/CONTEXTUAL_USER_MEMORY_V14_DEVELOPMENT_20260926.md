---
version: v14.0
date: 2026-09-26
status: IMPLEMENTATION_IN_PROGRESS
baseline_commit: 488a4291925c607f6d0dc313a7dcbaf1906a6fad
planning_commit: a1154d8
scope: MiLAi-Lab
---

# v14 语义边界开发记录

用户明确要求执行 [v14 Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v14.0_20260926.md)，原仅规划授权限制已由新指令取代。[实施基线](../data/manifests/contextual-memory-v14-baseline.json)确认 Git 基线的 46 份运行文件与 v13 最终映射相同，v13 结果清单引用证据及封存账本未改动。v13 的首次约定零卡/零持久来源、无回执审批措辞和持久正文临时引用问题继续保留。

一个 Sol xhigh 负责核心/Host/合同、配置和正式入口；主线程负责基线、输入冻结、真实模型控制、成本与报告。模型并发为 1。Luna high 沿用已有 Git 发布授权。本轮源码与模型已在本地，无须下载；不设置常驻审核代理。

| 工作包 | 当前安排 | 验证边界 |
| --- | --- | --- |
| A 未来用途及剩余处置 | 复用 maintenance.pending/frontier，增加最小 dispositions 与真实 write_facts | 首次直接观察均有处置机会；真实来源关联不等于整条消息全部意义处理完毕 |
| B 执行回执 | 复用 RuntimeStore intent/result，finish 声明 completed_action_refs/pending_actions | 结构回执与实际 answer 分别验收，不以查询/消息冒充另一业务完成 |
| C 自包含正文 | 已发布协议 token、有效原始来源支持的 literal_uses；CREATE/full REVISE/patch 新片段 | 不按 mN 外形全禁，不因真实重复型号出现多次拒绝；混合字面/指代仍要语义核对 |
| D 表达与身份 | 先离线定位重复，再收敛说明；独立 v14 notes/maintenance v5 与必要协议版本 | 同一可调用能力；旧活动身份不冒充新运行，原磁盘布局不重造 |
| V0—V3 | 开发后窄检查 → 冻结独立诊断 → 原 arc0 → 条件满足后两条新原生 arc | 原始输入、gold 隔离、费用与所有失败保留；不提前生成未见题挑样本 |

v14 费用使用新连续账本并引用封存 v13 的 56 次生成、345375 generation tokens、2797 embedding tokens，unknown=0、Judge=0。累计上限保持 null；单工作流容量仍有效。开发代理开销不混入 benchmark provider tokens。

截至首发开发快照，尚未生成 V1 诊断输入、未生成或读取 V3 新原生任务、未调用 v14 实验模型；此后的真实诊断见下文。最终必须分开核对 G1 首次保留、G2 不过度保留、G3 执行依据与真实措辞、G4 正文及字面碰撞。


## 零模型基线测量与运行准备

[固定请求拆分](../data/manifests/contextual-memory-v14-contract-baseline.json)读取 v13 R1 的 29 份真实请求：system 文本累计 86868 tokens、frontier 文本 7755；两者与其他历史材料的独立估计不直接加总为 provider 计费。稳定规则前缀为 790、工具目录 1915，动态主体尾部为 94—368。未来约定保留及业务完成/记忆保存的区别在多个位置重复；v5 将据此收敛，新增语义字段成本另外报告。初次统计脚本未考虑目录后面的主体尾部，JSON 解析报错后按真实边界修正；未涉及模型调用或运行源码。

[服务核对](../data/manifests/contextual-memory-v14-provider-baseline.json)确认部署为 vLLM 0.27.1 / xgrammar 0.2.3；实时配置指标显示 prefix caching=false。未重启或变更服务，未估算缓存/延迟收益。新 v14 连续账本已创建，累计上限为 null，引用封存 v13 的准确账本哈希。

[曝光及前瞻规则](../data/manifests/contextual-memory-v14-exposure-rule.json)只读取历史选择与原始制品的身份字段，汇总 36 项记录；已暴露 base_seed 为 0、1、2。只有 V1/V2 满足 G1—G4 后，才生成最小未暴露的两条原生 arc，并在请求前排除相同完整哈希；初始候选为 3、4，尚未生成/读题。运行失败不得换 seed 覆盖。

独立入口 [run_contextual_semantic_v14.py](../tools/run_contextual_semantic_v14.py)使用正式 TaskTurn/task_runtime 和可信本地工具结果。它不读取 rubric/expected future_use，不设置 persistence_required；每例隔离运行库、按正式 session 边界关闭/重开，失败保留制品及费用。入口源通过单文件 Ruff/mypy；尚未生成诊断输入、未运行模型。此检查只证明接线与静态属性，不算语义成功。

## 本次 GitHub 开发快照

用户要求由 Luna high 将全部当前开发提交到 `minguselandy/MiLAi`。本次快照仍为 `IMPLEMENTATION_IN_PROGRESS`，不关闭 v14 Goal，也不声明研究基线已通过语义验收。核心改动已经接入正式路径：

- A：maintenance-v5 复用现有 pending/frontier，提供 unhandled_candidates、dispositions、write_facts；预检与实际 finish 使用同一语义校验入口。
- B：execution_facts 来自实际 journal 和当前已交付来源；completed_action_refs 仅接受已交付的成功回执，包括当前明确展开的合法既往回执。HostResult 分开保留 answer、完成引用和 pending_actions。
- C：写入前检查已发布的临时 token；literal_uses 需有有效写入依据及已交付原始字符支持。patch 仅检查新增片段，未改动的旧正文污染单独报告。
- D：独立 v14 notes 模板及 prepare/MERIT 入口已接线；config 为 contextual-task-v14、maintenance 为 turn-maintenance-v5、write 为 contextual-write-contract-v14。现有身份校验区分新旧运行。

核心负责人执行的受影响检查：

```bash
.venv/bin/python -m pytest -q --tb=short \
  tests/unit/test_contextual_turn_maintenance.py \
  tests/unit/test_contextual_content_patch.py \
  tests/unit/test_contextual_host_adapter.py \
  tests/unit/test_contextual_runtime_recovery.py \
  tests/unit/test_contextual_v9_prepare.py \
  tests/unit/test_contextual_merit_adapter.py
```

结果为 **88 passed**；同批 12 个改动源码/测试文件 Ruff 通过，8 个源码文件 mypy 通过，`git diff --check` 通过。独立诊断入口的单文件静态检查另见上文；新增四份 manifest 与 notes 模板 JSON 解析通过。未运行全套测试、构建或 v14 实验模型。

后续仍需部署 decoder 检查、合同压缩后的同口径 token 对照、开发完成后冻结的 V1 独立诊断、V2 原 arc0，以及满足语义门槛后才开展的 V3。结构检查不能证明自然语言答案真实或混合来源已被完整处置。改动均限于 Lab，未改变 Product Schema/API/权限/Canonical，也未移动包或引入跨 bundle 依赖；未另跑边界全套。回退基点为本快照前的 `a1154d8781fb3c25ffaa397cff2f5e688fa57cd1`。原始日志、数据库、模型、数据集与运行制品继续保持 ignored。

## 发布后续开发与 V1 首批

`23132fb` 已由 Luna high 发布到 GitHub，远端核对完成。其后的 D 检查修正了最终阶段文字目录仍显示全部工具的问题：目录现与同轮实际 schema/dispatcher 使用相同可调用集合；另修正字面出处的子串误判及 task-local 正文误禁。受影响检查 70 passed；这是与先前 88 项重叠的检查，不相加为独立测试数。

[合同检查](../data/manifests/contextual-memory-v14-contract-checks.json)保留同一 v14 schema、同一状态的零模型前后测量：普通 system 2493 → 2165 tokens，总输入 2818 → 2490；强制结束 system 2492 → 684，总输入 2860 → 1052。结束阶段 schema 本来只允许 finish，变化使文字目录与之对齐。新语义字段已包含在绝对值内；不把与 v13 的语义差异算成压缩收益。部署 vLLM 0.27.1 / xgrammar 0.2.3 的 11 个正反语法探针通过，无生成费用。

随后冻结[公开输入规范](MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_INPUTS_20260926.md)、[独立评审规范](MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_RUBRIC_20260926.md)和[身份清单](../data/manifests/contextual-memory-v14-diagnostic-freeze.json)：12 个自建虚构实例、20 个会话，评分标签不进入 Host。先执行 d01/d05/d12，未执行原生 V2/V3。

[R1 首批](../data/manifests/contextual-memory-v14-v1-r1-results.json)：d01 正确回答计算且关闭后零卡/零来源；d05 首次保存 Cedar 约定，新会话与独立进程可读取，未提前发议程；d12 三次未声明 literal_uses 而遭拒，零卡且 no_progress。该失败揭示真实字面值保留路径不可用，不能称为语义通过。R1 共 7 次生成、22643 generation tokens、125 embedding tokens，47 份运行源码已保存为忽略的证据快照。

R2 仅修正通用失败反馈：保留两类具体错误码，既有 repair_of 指导说明自包含改写与有效字面出处两条路径；实际 JSON-action 窄检查 2 passed。同期恢复 unsaved 的来源保留限定。[R2 同一已暴露碰撞例](../data/manifests/contextual-memory-v14-v1-r2-results.json)仍失败：work_note 明确选择 literal_uses，但实际动作遗漏；还出现未提交的无依据日期参数及错误修复 ID。增加 3 次生成、10103 tokens、零 embedding，累计 10 次 / 32746 / 125，unknown=0、Judge=0。

后续零生成探针确认：当前有序解码 schema 不允许在 subject/persistence/repair_of 之后追加 literal_uses。下一步仅调整该可选异常字段的位置并验证，不改输入、评分、服务或来源内容。两次失败及完整费用保留。当前仍为 IMPLEMENTATION_IN_PROGRESS，V1 有未关闭反例，不能进入 V3 或宣称 baseline ready。

R3 将 literal_uses 移到 repair_of 之后，能力与校验不变；两项针对性检查通过。[相同参数顺序探针](../data/manifests/contextual-memory-v14-literal-order-check.json)从拒绝变为接受，11 个部署语法探针也通过。排序后的语义 schema digest 不感知 property 顺序，因此另保存有序 schema SHA 与源码身份。[真实碰撞复验](../data/manifests/contextual-memory-v14-v1-r3-literal-results.json)完成两会话：第一次缺声明被拒，随后明确字面出处而写入，独立进程能读回正确型号及连接器关系。增加 4 次生成、13597 tokens、92 embedding；仍保留一次拒绝及此前两轮失败。

[R3 其余九例](../data/manifests/contextual-memory-v14-v1-r3-remaining-results.json)全部完成 Host 流程，但语义／任务评审发现三个反例：d02 的真实 MSG-K17 已在工具输出及持久来源中，正文和答案却用内部 call ID 代替业务回执；d04 没有将所要求的 READY 真正放在回答末尾；d11 将同条消息中的下次 Atlas 提醒存为 task，来源因此退出候选，关闭后丢失。d03/d06/d07/d08/d09/d10 在声明范围内通过；d08 有一次 u0 正文引用拒绝后正确改写。d02 的独立进程已完成 turn 重放返回原结果，没有重复业务或模型调用，这只证明恢复保障，不抵消回执语义错误。

截至该阶段，累计 39 次生成、130052 generation tokens、992 embedding tokens，unknown=0、Judge=0。当前继续修正 task 写入后的处置缺口与终结合同中的业务 ID、实际答题边界；仅复验三个已暴露失败例。所有输入和 rubric 保持原冻结字节，未运行 V2/V3，未改变原生数据／评分。已成功路径与失败路径有不同源码身份，不能将它们描述为同一最终版本的完整验证。

## R4 复核与当前发布状态

R4 使 task 写入后的来源继续参与未来用途处置，并明确其 `future_session_available=false`；finish 合同区分内部动作引用与外部业务回执 ID，要求 answer 实际履行用户请求。两项针对性检查及受影响静态检查通过。[三个已暴露失败例的复核](../data/manifests/contextual-memory-v14-v1-r4-results.json)仍未关闭全部反例：

- d02 正确保留和回答 MSG-K17，但第二会话新增“包裹仍在 6 号位”的无依据状态。消息送达不证明实际仓储状态，G3 仍失败。
- d04 仍未把 READY 放在回答末尾；关闭后零持久记忆，G2 通过，但用户任务未完成。
- d11 已能看到 task 写入不会跨会话保留，仍明确将下次 Atlas 提醒判为 task_local；关闭后提醒丢失，G1 仍失败。

本轮新增 10 次生成、35841 generation tokens、278 embedding tokens；v14 连续累计为 **49 次生成 / 165893 generation tokens / 1270 embedding tokens**，unknown=0、Judge=0。所有失败、输入及 rubric 原冻结字节保留，没有合并不同源码轮次的有利结果。

限定的一次 Astra xhigh 只读诊断确认上述失败不能归因于动态合同漏发或会话恢复，并发现 COMMON_PROMPT 的旧句 `Keep temporary plans in the conversation or task State.` 与按未来会话用途决定持久性的合同存在冲突。删除该冲突句是后续具体修复建议，尚未实施或验证；不据此宣称 d11 已修复。d02、d04 没有发现新的确定性机制断点，不安排无依据的重复运行。

准备 V2 时另发现并修复了确定性业务回执接线问题：原 Host 将 Observation.artifact 当作工具名，但正式 MERIT 来源使用自定义 artifact。当前改为将可见 source 与实际 raw/reconciled journal 动作及完整 Observation 核对；合法自定义 artifact 回执可以使用，错误身份来源仍被排除。Sol xhigh 的 4 项受影响窄检查及 Ruff、mypy、`git diff --check` 通过；未运行模型。该修复发生在 R4 真实运行之后，不能将 R4 结果归属于此后的源码。

本次再次按用户要求交由 Luna high 提交并推送全部当前开发。仍为 **IMPLEMENTATION_IN_PROGRESS**：上述语义反例、冲突句修复及最终源码下的 V2 原始世界／空记忆完整 arc0 尚未完成；V3 未运行，其语义门槛尚未满足。发布不增加实验请求，不扩大测试范围，不关闭 Goal。改动仍仅限 Lab，未改变 Product Schema/API/权限/Canonical，也未增加跨 bundle 依赖或移动包；未运行全套测试、构建或边界套件。此次提交前回退基点为 `23132fbf6bf3e451bf4e14537c1f4f6b83efacc5`；原始运行制品、数据库、模型和语料继续保持 ignored。
