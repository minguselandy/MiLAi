# MiLAi vNext 后续开发规划
## 基于 LangGraph / LangMem 公共基线的选择性适应方法重构

- 日期：2026-09-26
- 状态：`PLANNED_NOT_STARTED`
- 规划依据：MiLAi main 0802d34f49db45bd654fc745d33da3252c0d4e24；LangMem upstream 9d033b47d9ce53e37e92c92241b0496c0278932e
- 文档性质：后续开发上位规划；不代表已执行、已验证或已提交的 v15+ 工作。

## 执行摘要

本规划建议停止继续扩展当前自研 ordinary memory runtime，把 v14 作为 reference implementation 和失败证据保留；新的研究主线在 MiLAi-Lab 中建立一个公开、可复现的 LangGraph + LangMem baseline，再以最小增量加入 MiLAi 的 evidence-grounded decision state、selective recheck 和 State-Attention。Product 不迁移、不改 Schema/API/权限；Artifact-Archive 继续只承担历史证据。

这一调整不是否定 v6-v14 的开发。相反，当前实现已经把问题暴露得足够清楚：来源、版本、CRUD、恢复、业务日志和维护合同已经能够工作，但 semantic frontier 仍会把未来需要的事项判为 none/task_local，业务执行后 CURRENT 记忆也可能保持过时。继续给自研 baseline 增加 prompt、frontier 字段和修复合同，边际研究价值已经明显下降。

后续主实验不再比较“无记忆 vs MiLAi”，而比较“公开强 memory agent vs 同一 agent + MiLAi 控制机制”。推荐四层：B0 Upstream LangMem、B1 Instrumented LangMem、M1 Sparse Decision Basis、M2 Basis + State-Attention。B1 只增加语义中性的 provenance/version instrumentation；任何“该不该记、何时更新、何时检索”的语义策略必须留在 treatment 中，避免把 baseline 悄悄修成 MiLAi。

Jev 暂不进入主方法。核心方法必须由当前 LLM 单独完整执行。只有当 M1/M2 在未见任务上证明有效后，才把 Jev 作为 bounded controller 的效率后端进行可选优化。

## 1. 文档依据、范围与结论边界

本规划基于 GitHub 当前 main 的仓库事实、v10-v14 结果与核心代码静态阅读生成，没有重新运行模型、pytest 或 benchmark，也没有修改仓库。所有“已实现/已验证”均限于对应提交和报告；所有“建议/目标架构”均为后续设计，不应写成现有能力。

仓库已经完成 Source of Truth 重组：MiLAi-Product 是可部署产品唯一实现，MiLAi-Lab 是研究与评测唯一实现，MiLAi-Artifact-Archive 只保存历史索引和恢复证据。Lab 不得导入 Product 私有实现；Product-faithful 实验只能通过公开接口/testkit并锁定身份。因而本规划全部新研究代码放在 MiLAi-Lab；Product 仅作为后续黑盒/公开接口实验对象，不作为这次方法开发底座。

## 2. 当前仓库状态与核心诊断

当前 main 为 0802d34。v14 状态为 IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES。最终源码从原始世界、空记忆跑完已暴露 MERIT arc0：native 4/5、dependent 1/2、Host/maintenance 7/7。两项首次未来约定 0/2 保留；episode 4 真实退款成功后，唯一 CURRENT 卡仍保留“尚未处理”的过时状态。V3 因 readiness gate 失败而未运行。

v14 证明的关键事实不是“存储接口坏了”，而是“结构要求已经足够严格，LLM 仍会做错语义选择”。semantic_frontier 会列出 unhandled_candidates，finish 必须给出 task_local/cross_turn/durable/none disposition；cross_turn/durable 还要求有真实 durable record。然而 Host 仍能合法地把未来事项错误判成 none/task_local。换言之，forced disposition != correct memory policy。

v10-v11 则证明 Decision Basis 机制本身可进入真实 ReAct，但未建立质量收益：v10 R2 出现 adoption -> new observation -> recheck -> committed revision 的真实链，notes 5/5、basis 4/5，basis 更贵；v11 已实现 nullable critical_gap、program-owned recheck、状态 no-op、compact projection 和 explicit-query-first gap retrieval，但完整比较仍未观察到自动 gap search 或 version notice 的稳定增益。

## 3. 为什么不应继续扩展当前 ordinary runtime

当前 contextual 研究路径已经从“方法原型”膨胀为一套自建 Agent memory platform。静态统计显示：contextual_user_memory.py 约 2,311 行，contextual_host.py 约 2,406 行，contextual runner 约 1,630 行；围绕 contextual 路径有 30+ 个源码模块和 24 个专项测试文件。Lab 整体还包含大量历史 configs、tools、studies 和结果文档。继续在这条路径上修 baseline，会持续产生维护、复现和因果归因成本。

尤其不应再为 baseline 追求“语义完美”。一个公开 baseline 的任务是提供真实、代表性的强对照，而不是在看到 MiLAi 的失败案例后逐条把 baseline 修到通过。以后如果 LangMem 在 future commitment、reconciliation 或 action grounding 上失败，这首先是 baseline 行为；只有会同时影响所有实验臂的机械问题（模型接入、身份、计费、业务工具、数据泄漏）才作为 shared infrastructure 修复。

当前 v14 代码和历史不能删除。它应被冻结为 reference implementation，用于 failure archaeology、确定性 regression 和对照新系统是否重现已知错误；但新研究功能不再继续落到 contextual_user_memory.py / contextual_host.py / maintenance-v5 这条大路径上。

## 4. 保留、冻结与退出活动开发面的边界

| 仓库/能力 | 后续处置 | 原因 |
| --- | --- | --- |
| MiLAi-Lab benchmark/scorer/adapter | 保留并复用 | 这是已有最强资产：原生任务、评分、暴露边界、成本和冻结身份 |
| v14 12-case semantic diagnostic + rubric | 保留为 development diagnostic | 覆盖 task_local/cross_turn/durable、执行依据和字面碰撞；不当 benchmark |
| MERIT adapter / native checker / world identity | 保留并复用 | 用于真实业务动作和跨 episode 持续性 |
| Artifacts/manifest/budget accounting | 保留并复用 | 确保失败、token、版本、输入身份可追溯 |
| v14 contextual ordinary runtime | 冻结为 reference arm | 不再继续扩功能；用于历史回归和失败取证 |
| v10/v11 Decision Basis / State-Attention 代码 | 作为算法参考，不直接搬整套 runtime | 关键语义已经实现过；新实现只抽取纯机制 |
| H1-H6/support/events 旧候选 | 冻结 | 除非新的实验结果明确触发，不恢复候选矩阵 |
| MiLAi-Product | 不改动 | 遵守 Source of Truth；仅公开接口黑盒实验 |
| Artifact-Archive | 只读 | 不作为 runtime/import dependency |

## 5. 公共 baseline 选择：LangGraph + LangMem

推荐将 LangGraph + LangMem 作为新的工程 foundation 和 primary public baseline。已核对 LangMem 当前 main 提交 9d033b47（2026-09-09），项目版本 0.0.30，MIT 许可，依赖 langgraph>=0.6,<2。LangMem 提供 hot-path create/update/delete memory tool 和 search memory tool，也提供 memory manager；LangGraph 提供 stateful agent、long-term Store 和 durable/checkpoint execution。

选择 LangMem 的主要理由不是“它一定最好”，而是它满足研究需要：公开、成熟、可引用；CRUD/search 足够强；与 ReAct/长期 store 集成自然；而且尚未预先实现 MiLAi 想验证的 evidence-grounded decision state、adopted exact versions、selective recheck 和 decision-gap attention。它能让 baseline 强而不过度吞噬方法空间。

不建议把 ReMe、Graphiti、Letta 或 MemOS 作为主 foundation。ReMe 和 Mem0 更适合作为后续 external baselines；Graphiti 的 temporal graph 会引入过多关系建模变量；Letta/MemOS 则会连 Agent runtime 一起替换，难以保持研究归因。

## 6. 目标实验分层

| Arm | 共享基础 | 额外机制 | 角色 |
| --- | --- | --- | --- |
| B0 Upstream LangMem | LangGraph + LangMem + 同一 LLM + 同一业务工具 | 无 MiLAi 改动 | 公开外部 reference baseline |
| B1 Instrumented LangMem | B0 | 仅 provenance/version/receipt instrumentation；不得改变模型语义选择 | 主 matched baseline |
| M1 Sparse Basis | B1 | Evidence-Grounded Decision Basis + selective recheck；普通 retrieval | 验证决策状态本身 |
| M2 Basis + State-Attention | M1 | critical-gap retrieval + selective expansion/stop | 验证 Attention/control 增量 |

主因果比较是 B1 -> M1 -> M2。B0 用于回答“原生 LangMem 自己能做到什么”。任何 B1 instrumentation 必须先做 parity gate：在同样模型输出和工具调用下，不应改变 upstream create/update/delete/search 的语义结果；只允许增加隐藏的 revision/provenance/receipt 记录。

## 7. 目标 vNext 架构

目标架构不再自建整套 Agent runtime，而是在 LangGraph/LangMem 上增加薄的 MiLAi control layer。建议逻辑关系如下：

```text
User / Tool Observation
        |
        v
LangGraph ReAct Agent
  |             |
  |             +--> LangMem search/manage_memory
  |
  +--> MiLAi Decision Basis (task-local, sparse)
            |
            +--> adopted evidence @ exact revision
            +--> critical action-sensitive gap
            +--> recheck reasons
            |
            v
      MiLAi State-Attention
            |
            +--> default search
            +--> gap-directed search
            +--> read / act / no-op
        |
        v
Business tool receipts + LangMem updates
        |
        +--> version/provenance wrapper
        +--> selective recheck candidate
```

程序仍只保证机械事实：source identity、exact revision、可见范围、业务 receipt、实际 CRUD result。LLM 决定语义：当前判断是什么、哪些材料被实际采用、gap 是否会改变行动、是否需要创建/更新/删除/不操作。Jev 不参与这条主链。

## 8. 新代码组织建议

建议在 MiLAi-Lab 中新增独立 vNext 包，避免继续修改 giant contextual runtime。旧 contextual 文件保持 reference-only。下面是建议路径，不要求一次全部建立：

```text
MiLAi-Lab/
  src/milai_lab/
    baselines/
      langmem_adapter.py
      langmem_types.py
    methods/
      milai_vnext/
        provenance.py
        versioned_store.py
        decision_basis.py
        selective_recheck.py
        attention.py
        controller.py
    runners/
      milai_vnext_agent.py
    datasets/                 # 复用现有 MERIT/MemSyco adapter
    scorers/                  # 复用现有 native scorer
  configs/
    langmem-baseline-v1.json
    milai-vnext-basis-v1.json
    milai-vnext-attention-v1.json
  data/locks/
    langmem-foundation.lock.json
  tools/
    prepare_milai_vnext.py
    run_milai_vnext_merit.py
  docs/
    MILA_LANGMEM_FOUNDATION_GOAL_v15.md

```

不要 vendor LangMem 源码，也不要在仓库中保存第三方 clone。依赖写入独立 dependency group（例如 baseline-langmem）并由 uv.lock 固定；lock manifest 另外记录 upstream commit、PyPI/package versions、license 和关键文件 SHA。

## 9. 分阶段开发计划

| 阶段 | 目标 | 核心交付 | Go 条件 | 禁止项 |
| --- | --- | --- | --- | --- |
| P0 Freeze | 冻结现有 reference | v14 identity、失败、成本、reference runner；新 vNext Goal | 0802d34 可复核；旧结果不改写 | 不再给 contextual runtime 加语义新功能 |
| P1 Foundation Spike | 验证 LangMem + 本地 vLLM 可行 | 依赖锁；最小 ReAct；manage/search；业务工具；两轮 checkpoint | 一条 create/search/action/restart 闭环可跑 | 不改 benchmark、不加 MiLAi 机制 |
| P2 B0 Characterization | 跑 upstream LangMem | v14 diagnostic + exposed MERIT arc0 的 baseline 结果 | 完整记录质量/失败/成本 | 不因失败逐题修 LangMem 语义 |
| P3 B1 Instrumentation | 增加语义中性 provenance/version | Observation ID、memory revision history、receipt trace、parity tests | 与 B0 模型动作语义一致；instrumentation 可追溯 | 不加 future-use 规则、不加 recheck policy |
| P4 M1 Sparse Basis | 验证决策状态 | sparse basis、exact adopted revision、program-owned change notice、same-response delta | 机制可达且不强制每轮 State | 不加额外 reflection Agent |
| P5 M2 Attention | 让 State 真正改变取材 | gap-directed search、explicit-query priority、bounded recheck | 存在自然 gap -> 不同检索/行动链 | 不自动把 gap 当 truth/persistence/delete 权限 |
| P6 Frozen Eval | 做 matched 未见验证 | B1/M1/M2 在预注册 MERIT + MemSyco 子集上的结果 | 未见样本、同信息/预算、完整成本 | 不换题覆盖失败、不 post-hoc 调 prompt |
| P7 External Baselines | 外部可比性 | Mem0 / ReMe 原生 adapter（按需要） | 主机制先出现信号再扩展 | 不同时集成大量系统 |
| P8 Efficiency | 后续效率优化 | 可选 Jev controller backend | LLM-only 方法已成立 | 不将 Jev 作为主方法成立条件 |

## 10. P1 Foundation Spike 的具体技术门槛

LangMem 迁移最大的未知不是 memory API，而是本地 Qwen/vLLM 与 LangGraph 的工具调用兼容性。当前 MiLAi 使用自定义 JSON-action + xgrammar；LangGraph/LangMem 示例通常依赖标准 tool calling。因此迁移的第一步必须是 compatibility spike，而不是直接开始重写 benchmark runner。

Spike 只做六件事：1) 用本地 vLLM OpenAI-compatible endpoint 调 LangGraph agent；2) 普通回答；3) 一次业务工具调用；4) 一次 LangMem create/update/delete 中至少 create；5) 一次 search；6) 两轮/重启后仍能读到长期 memory。所有请求计费，但不进入方法结果。

如果 native tool calling 不可靠，允许退回“LangMem functional core / BaseStore + 现有 VLLMClient 的薄适配器”。但 fallback 的目标是继续复用公开 memory core，不是把 contextual_host.py 的 2.4k 行重新搬进新架构。若为了接入 LangMem 需要复制现有 Host/maintenance/runtime 的大部分逻辑，则 foundation 方案判定为不合格，需要重新选择 baseline。

## 11. B1 instrumentation 的最小语义

B1 是公平实验的关键。它只允许增加模型不可见或所有 treatment 同样可见的事实性 instrumentation。建议最小对象：

```text
ObservationRef:
  source_id
  role / actor
  session_id
  content_hash
  optional timestamp

MemoryRevision:
  memory_id
  revision
  content
  source_refs
  created_at
  supersedes_revision

ActionReceipt:
  call_id
  tool_name
  status
  selected identity arguments
  output/source_ref
```

B1 不应加入 support groups、conditions engine、ChangeSet graph、semantic frontier、future_use 分类器或自动 reconciliation。否则又回到自建 baseline。需要更复杂证据关系时，必须由 M1/M2 的具体假设触发并通过消融证明价值。

## 12. M1：Evidence-Grounded Decision State

M1 应直接复用 v11 已经验证过的收敛思想，而不是重新设计字段。首版只维护一个 task-local active decision；仅当存在 action-sensitive uncertainty 时激活。字段固定为 decision、scope、adopted_evidence、critical_gap、status。critical_gap 可以为 null；程序拥有 recheck reasons，Host 不直接声明 needs_recheck。

adopted_evidence 必须绑定“实际交付给 Host 的 exact revision/source span”，不能自动跟随 latest。若 memory_id@3 被更新为 @4，当前 decision 仍保留 @3，并产生 recheck reason；只有 Host 在后续正常 ReAct 中读到合法材料并重新采用，才切换到 @4。

M1 不增加单独模型调用。state delta 与正常 action 在同一 LLM 响应产生；相同规范化状态视为 NO_STATE_CHANGE。没有 action-sensitive gap 时允许没有 active decision，Basis activation rate 越低不代表失败。

## 13. M2：State-Attention

M2 只研究“当前决策缺口如何改变信息获取”，不重新定义 storage。检索优先级：explicit query > actionable critical_gap > default task query。gap-directed query 由结构化 scope/item/gap 组成，首版不增加检索 Planner Agent。

Attention 的输出不是事实裁决，也不授予写入/删除权限。它只决定：当前材料是否足以行动、是否需要进一步 search/read、优先展开哪个候选、是否可以暂缓某个不影响当前行动的未知。

首版必须保留 ordinary search fallback，防止错误 State 自我确认。测试重点不是“gap search 次数”，而是：错误/不完整 State 下能否通过新观察和普通检索恢复；gap search 是否真实改变后续 evidence/action；无需要时能否不介入。

## 14. 数据与实验顺序

开发期先复用 v14 的 12 个冻结语义诊断和已暴露 MERIT arc0；它们只用于 wiring/regression，不计未见证据。v14 报告明确未生成/读取 seeds 3/4；若在新方法冻结前仍保持未暴露，应在 selection manifest 中先按 seed/hash 前瞻冻结，再生成/运行，不能先读题挑有利样本。

正式小样本建议：MERIT 用于真实工具动作、跨 episode 消费和 post-action state；MemSyco 用于 scope/valid-memory/personalization，保持原生输入和 gold 隔离。LongMemEval 可作为补充 recall/update 评估。StateMemBench 在当前仓库记录中仍是 NOT_RUN/不可核验，不应成为主计划依赖。

外部 baseline Mem0/ReMe 只在 M1/M2 出现机制信号后加入。否则先集成多个系统会把时间消耗在适配，而不是验证核心假设。

## 15. 评价指标与质量-成本边界

| 维度 | 主指标 | 解释 |
| --- | --- | --- |
| 原生任务 | MERIT native success / dependent success；MemSyco native score | 不能用维护完成替代任务成功 |
| 保留/更新 | first-retention accuracy、stale-current rate、valid-memory preservation | 同时看漏改与误改 |
| 决策状态 | basis activation rate、decision churn、adopted-evidence validity | 结构 State 不应每轮更新 |
| 重核 | recheck precision / recall、recheck outcome | 版本变化不等于原判断错误 |
| Attention | gap utility、extra search/read、missed necessary retrieval | 调用更多不是收益 |
| 行动依据 | receipt-grounded completion claims、false completion claims | 计划/消息/查询不等于实际动作 |
| 成本 | input/output tokens、calls、embedding、latency、storage | 报告总生命周期成本，不只最终回答 |
| 质量-成本 | 同预算质量、同质量成本、复用次数 N 下累计成本 | 形成可解释 Pareto 边界 |

## 16. 版本、复现与 CI 计划

所有 vNext 实验都必须有三层身份：MiLAi repo commit/source mapping、upstream foundation lock、运行 config/data/model identity。LangMem source audit 固定提交 9d033b47；实际 Python 包精确版本由 MiLAi-Lab 的 uv.lock 固定，不能只写“latest LangMem”。

建议新增 dependency group `baseline-langmem`，避免把 LangChain/LangGraph 全部依赖强加到默认 Lab core。CI 新增一个窄的 langmem-foundation job：安装该 group，执行 import/boundary/parity/adapter tests；现有 active-package 和 historical regression job 保持。

不把第三方源码复制进仓库；不提交模型、数据库、原始 transcripts 或运行目录。实验只提交 compact manifests、冻结 config、选择 identity、结果摘要和可复现命令。

## 17. 风险与缓解

| 风险 | 早期信号 | 应对 |
| --- | --- | --- |
| vLLM tool calling 与 LangGraph 不兼容 | schema/tool call 无法稳定解析 | P1 立即 fallback 到 LangMem functional core + 薄 VLLM adapter；不复制旧 Host |
| LangMem baseline 太弱 | 明显漏存/乱更，但技术链正常 | 保留为 B0；B1 只做 instrumentation；不要逐题语义修复 |
| instrumentation 改变 baseline | B0/B1 行为分叉但没有 MiLAi 控制 | parity test；wrapper 默认 model-invisible；若模型可见则所有 matched arms共享 |
| M1 仍只是 structured scratchpad | B1 notes 与 M1 持平 | 接受负结果；不要继续加字段；转向 Attention 或终止机制 claim |
| M2 形成确认偏差 | gap query 只找支持当前判断材料 | 保留 default retrieval fallback；错误-State stress；balanced evidence |
| 成本再次膨胀 | Basis activation/churn 高、输入重复 | sparse activation、compact projection、no separate call；成本作为 gate |
| 未见样本被调参污染 | 失败后修改 prompt 再重跑同 seed | 一旦用于修复即转 development；重新冻结未见 selection，不替换失败样本 |
| 研究和 Product 混淆 | Lab 导入 Product private code | 保持 SOURCE_OF_TRUTH；Product 只通过公开接口/testkit+lock |

## 18. Go / Pivot / Kill 决策规则

| 门槛 | GO | PIVOT | KILL / STOP |
| --- | --- | --- | --- |
| Foundation | LangMem baseline 可通过同一 vLLM/business/checkpoint 路径运行 | functional-core adapter 可行 | 接入需要复制旧 runtime 大部逻辑 |
| M1 | 相对 B1 在 selective adaptation/保持上有可重复信号，成本可接受 | 只有 provenance/version 帮助 -> system/reliability 方向 | B1 notes 持平/更好且 mechanism ablation 无影响 |
| M2 | gap/recheck 真实改变 evidence/action 并改善任务或降低重复成本 | 只改善 retrieval -> retrieval-control 论文 | Attention 不触发、只增成本或放大错误 State |
| Formal | 未见样本 + 第二任务族保持方向 | 只在单域有效 -> 明确边界/系统论文 | 优势只来自额外信息、更多调用或 benchmark exposure |
| Efficiency | LLM-only 方法成立后再优化 | 仅成本收益 -> efficiency extension | 不允许 Jev 挽救无效主机制 |

## 19. 建议的连续 Goal 划分

为了避免再次出现一个 Goal 同时重构 runtime、修 baseline、加方法并跑 benchmark，建议把后续工作拆成三个可独立结项的 Goal。

| Goal | 名称 | 只做什么 | 结项条件 |
| --- | --- | --- | --- |
| v15 | LangMem Foundation & Public Baseline | P0-P2：依赖锁、兼容性 spike、B0 adapter、语义诊断/arc0 characterization | 公开 baseline 可运行、身份/成本可复核；不要求语义全通过 |
| v16 | Evidence-Grounded Selective Recheck | P3-P4：B1 instrumentation + M1 sparse basis | B1 parity + M1 机制可达；冻结后才进入小比较 |
| v17 | State-Attention & Matched Evaluation | P5-P6：M2 + B1/M1/M2 未见 matched eval | 明确质量/成本/失败边界，允许负结果 |
| v18 可选 | External Baselines & Efficiency | Mem0/ReMe；必要时 Jev backend | 只有 v17 发现值得保留机制后启动 |

## 20. v15 的立即执行清单

v15 不应再次修 v14 semantic frontier。建议严格按以下顺序执行：

1. 建立新的 Goal 和 foundation lock，声明 v14 reference freeze；不修改 Product。
2. 在独立 dependency group 中加入 LangMem/LangGraph，并记录 upstream commit、license、resolved package versions。
3. 完成本地 vLLM compatibility spike：普通回答、业务工具、manage_memory、search_memory、两轮 checkpoint/restart。
4. 实现最薄 B0 adapter，把现有 MERIT TaskTurn/world/checker 接到 LangGraph agent；保留原生任务输入、工具和评分。
5. 将 v14 12-case diagnostic 跑在 B0 上，只做行为 characterization，不据失败修改任务或 gold。
6. 用已暴露 arc0 跑一次 B0 regression；记录 first-retention、stale memory、action grounding 和完整成本。
7. 冻结 B0 实现和结果。若 foundation GO，再设计 B1 instrumentation；否则停止并重新评估 ReMe/Mem0 作为 foundation。

## 21. 明确不做的事情

- 不继续在 contextual_user_memory.py / contextual_host.py / maintenance-v5 上叠加新语义功能。
- 不删除 v6-v14 历史、失败、manifest 或账本；它们继续是 reference evidence。
- 不把 v14 frontier/disposition 全量迁入 LangMem baseline。
- 不为得到 baseline 5/5 增加订单、金额、题号或 benchmark-specific prompt 规则。
- 不在 v15 引入 Jev、训练 controller、第二审核 Agent、图数据库或多 Agent reflection。
- 不同时集成 Mem0、ReMe、Graphiti、Letta；先验证 foundation 和核心方法。
- 不消费未见 MERIT seeds 3/4，直到方法和 selection protocol 冻结。
- 不把“Host complete”“maintenance complete”“引用合法”当成语义正确或任务成功。

## 22. 论文主线与开发主线的统一

如果后续 M1/M2 成立，论文贡献应围绕一个很窄的问题，而不是“我们做了一个完整 memory OS”：在一个已经具备公开 CRUD/search/long-term store 的 Agent 上，显式追踪当前决策实际采用的证据，并在证据变化时选择性重核，是否能改善持续任务中的适应与保持，并形成更好的质量-成本边界。

对应最多三项贡献：1) decision-grounded continual-memory failure formulation；2) sparse evidence-grounded decision state + selective recheck + gap attention；3) 在公开 baseline、真实工具任务和 scope/update benchmark 上的 matched 质量-成本证据。LangMem、版本化 store、benchmark adapter、恢复和 Jev 都不应被包装成核心 novelty。

## 附录 A. 主要核对来源

- **R1** MiLAi main @ 0802d34: https://github.com/minguselandy/MiLAi/commit/0802d34f49db45bd654fc745d33da3252c0d4e24
- **R2** MiLAi root Source of Truth: https://github.com/minguselandy/MiLAi/blob/0802d34f49db45bd654fc745d33da3252c0d4e24/SOURCE_OF_TRUTH.md
- **R3** MiLAi repository map: https://github.com/minguselandy/MiLAi/blob/0802d34f49db45bd654fc745d33da3252c0d4e24/REPO_MAP.md
- **R4** MiLAi Lab README: https://github.com/minguselandy/MiLAi/blob/0802d34f49db45bd654fc745d33da3252c0d4e24/MiLAi-Lab/README.md
- **R5** v14 results: https://github.com/minguselandy/MiLAi/blob/0802d34f49db45bd654fc745d33da3252c0d4e24/MiLAi-Lab/docs/CONTEXTUAL_USER_MEMORY_V14_RESULTS_20260926.md
- **R6** v14 semantic-boundary design: https://github.com/minguselandy/MiLAi/blob/0802d34f49db45bd654fc745d33da3252c0d4e24/MiLAi-Lab/docs/MILA_CONTEXTUAL_USER_MEMORY_V14_SEMANTIC_BOUNDARY_DESIGN_20260926.md
- **R7** v11 sparse-basis results/design: https://github.com/minguselandy/MiLAi/tree/0802d34f49db45bd654fc745d33da3252c0d4e24/MiLAi-Lab/docs
- **R8** LangMem @ 9d033b47: https://github.com/langchain-ai/langmem/commit/9d033b47d9ce53e37e92c92241b0496c0278932e
- **R9** LangMem tools.py: https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/src/langmem/knowledge/tools.py
- **R10** LangMem pyproject / version 0.0.30: https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/pyproject.toml
- **R11** LangMem MIT License: https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/LICENSE
- **R12** LangGraph repository: https://github.com/langchain-ai/langgraph
