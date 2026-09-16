---
document_id: MILA-PRODUCT-01
version: "1.0"
status: SUPERSEDED_AS_ACTIVE_EXECUTION_BY_MILA_PRODUCT_02
document_type: PRODUCT_DEVELOPMENT_GOAL
title: 本地可用性与简单精准召回闭环
created_at: "2026-09-01T20:05:35+08:00"
repository: MiLAi-Product
parent: MILA-PRODUCT-GOALS@1.0
product_version: 0.1.0-candidate
product_tree_sha256: 3eee15bd165c6bcdb60c30ae4f002c1364c1acf073da8042d3653baafce08eca
schema_status: 0.1.x_EXPERIMENTAL_NO_GO_FOR_FREEZE
execution_authorized: true
execution_activation: USER_REQUEST_2026-09-01
activated_on: "2026-09-01"
formal_holdout_authorized: false
public_api_change_authorized: false
database_schema_change_authorized: false
default_feature_enablement_authorized: false
benchmark_owner: MiLAi-Lab
development_policy: REPAIR_SIMPLIFY_CONTINUE
audit_policy: MINIMUM_SUFFICIENT_EVIDENCE
---

# MiLAi Product-01：本地可用性与简单精准召回 Goal

## 1. Goal 定位

本 Goal 是 [Product Goals](../PRODUCT_GOALS.md) 的第一个产品交付子目标，不是新的项目级
Master，也不重新执行仓库拆分。

它只解决两个问题：

```text
1. 当前 Product 能否稳定完成一条真实本地 Memory 纵向链路？
2. 在身份、权限和 Reader 可见内容都真实的条件下，最简单的正式读取路径能否准确召回？
```

方法命题是：

> 先接通并验证已经存在的 Evidence、Canonical、FTS、Dense、lease heartbeat、RRF 和
> atomic context 能力；只补结构化身份、grounded relation Binding 与 EvidenceSet 选择的
> 最短缺口。简单路径不能证明增益时保留 baseline，不增加模型 Planner、Formation 或多轮搜索。

本文件保留 Product-01 的历史合同与 S0-S4 事实。S0/S1/S2/S3 已通过；S4 已执行并结束为
`FAIL_S4_REPAIR_OR_KEEP_BASELINE`。后续修复和重新验证由 `MILA-PRODUCT-02` 规划，本文件不再
控制新的执行顺序。

## 2. 当前机器基线

### 2.1 已经完成，不再重复

```text
Product/Lab 仓库拆分                         PASS
Product → Lab/legacy import boundary          PASS
architecture/v1.0 bundle validation/lock      PASS
Runtime unit + contract                       599 passed, 1 optional skip
六个 adapters                                 326 tests passed
Runtime 与六个 adapters build                 PASS
Product behavior tree                         301 files
Product tree SHA-256                          3eee15bd...08eca
```

这些事实证明源码闭包、静态边界和基础单元行为可用，不证明真实 PostgreSQL 纵向链路或记忆
召回质量已经达到产品门。

### 2.2 仍需产品化闭合

- 当前拆分仓尚未在 fresh isolated PostgreSQL 上重跑 0048/0049、真实角色/RLS、并发、worker
  与 operations 全门。
- Python Client 的 `EvidenceCaptureRequest` 和 `AgentMemory._capture` 尚未完整传播结构化
  `speaker` 与 `source_context`；拥有真实 session/turn 身份的 Agent 调用仍可能退化到
  `source_ref` 推断。
- `evidence_source.py` 在身份未知时仍存在 `session_id=subject_id` 的 legacy fallback；该结果
  不能用于 adjacency 或语义效果评测。
- Dense、type-directed semantics、budget-stable context、progressive context 和 Formation
  均保持默认关闭；不得把“代码存在”写成“产品已启用”。
- Product 没有内置生成式 Reader。它生成受治理 `MemoryContext`；Host 或 Lab 才能执行一次
  Reader 调用。

### 2.3 历史实验对本 Goal 的约束

| 历史事实 | 可采用结论 | 不可采用结论 |
| --- | --- | --- |
| DG24：23 evidence groups 中 6 个合法 channel 未调用、1 个 cutoff、3 个任何 channel 未发现；另有 2 个 event-time proof failure | 简单 multi-channel 和 EvidenceSet 有真实机会 | 不证明答案提升 |
| DG25：最低 Binding precision `2/3`，8 个 arms 共 16 次 Wrong COMPLETE | 旧 acquisition/Binding 策略不可发布 | 不能因候选池有信息就放宽完成边界 |
| DG26：fixed pool/K=8 的 correct StateView rerank 丢失 1 个 baseline-correct group | 不优先投入 StateView reranker | 不否定多通道 acquisition |
| DG27：D1 precision `12/17`、known-false accepted=5、Wrong COMPLETE=1；D2/D3 丢 11 个正确组 | 模型解释不能直接获得 Binding authority | 后续 deterministic witness 不能替代 effect 结果 |
| DG28 lite：target candidate `4/7→7/7`，binding `3/7→6/7`，precision=1 | 小 quota union + dedup/RRF 值得产品验证 | 7-case replay 不足以 default-enable |
| MF02：Semantic Episode 直接表示有正增益；MD02 shadow 等价但 boundary H1 MISS | Formation 作为后续候选保留 | 不作为本 Goal 依赖或产品效果 |
| 历史 500-case：Raw `15/500`、Candidate `23/500` context success，失败分别为 `485/500`、`477/500`；Candidate Judge `7.0%`；`formation_applied=0` | 首先是 worker/容量与评测真实性问题 | 不能判断 MiLA 正常语义能力或 Formation 效果 |
| 后续 lease repair：slow batch 32/32 delivered、worker exit=0 | 当前已有 heartbeat/0048 修复，应隔离重验 | 不能跳过 split 后 current-head PostgreSQL gate |
| 旧 R4：session identity 折叠，raw trace 不等于 Reader-visible 内容 | 只可作 pipeline diagnosis | 旧 Context/Answer/Judge 不得 resume 或成为新 baseline |
| LongMemEval：470 answerable 中 300 个需要多个 gold sessions | 优化 EvidenceSet role coverage | 单一 global Top-1/Top-k 不是充分目标 |

MVP-01 的 24-case Context-only canary 曾达到 24/24 terminal，但 21/24 是明确的
`CONTEXT_BUDGET_INFEASIBLE`，没有调用 Reader/Judge，不能解释为召回质量。后续 100-request
warm run 的 evaluator/identity/receipt 合同不一致，也不能作为产品成功率。

因此，身份修复后必须生成新的 untreated baseline；旧 R4 和历史 500-case 都不得恢复执行。

## 3. 两个产品假设

### PRODUCT-H1 — Local Operational Usability

在 fresh isolated PostgreSQL、本地 Runtime、一个 persistent worker 和正式 MCP/OpenWorker
路径中，Product 可以稳定完成：

```text
init
→ doctor
→ start
→ capture Raw Evidence
→ projection terminal
→ governed recall / Context
→ inspect provenance
→ proposal / review / versioned correction
→ revoke / derived cleanup
→ restart / idempotent replay
→ stop
```

同时，慢批次与 lease renewal 不导致 worker 整体退出，模型不可用不破坏 deterministic
exact/FTS/Canonical 路径。

最小可信证据：fresh migration、真实角色 PostgreSQL tests、一条完整 golden flow、24 个产品场景、
100-request warm soak 和 restart/revocation/model-outage 负控。

### PRODUCT-H2 — Simple Grounded Recall Utility

在真实 source/session/turn identity、精确 Reader-visible trace 和相同预算下：

```text
Canonical exact
+ Raw FTS
+ optional Dense when configured
+ small per-channel quota union
+ identity dedup / RRF
+ same-session adjacency
+ grounded relation Binding
+ requirement-level EvidenceSet selection
```

相对 repaired untreated Product baseline，应提高多证据覆盖，并保持 Qwen Judge 非劣、严格
`Wrong COMPLETE=0`、权限/撤销/Canonical authority 零回归。

### 要排除的解释

本 Goal 必须排除以下伪增益：

- 更大的 Top-k、更多 hydration 或更多 Reader tokens；
- case ID、gold terms、手写 synonym 或 benchmark-specific regex；
- 重试、换 seed、重复投票或不同 Reader/Judge；
- 错误 session adjacency 或 Reader 实际未见的证据；
- 把 system failure、timeout 或 lease loss 计为 semantic abstention；
- Formation、reranker 或 Planner 暗中进入 treatment。

## 4. 六个硬边界

Product 不在每层增加新的防御状态机，只保留六个跨组件硬边界：

1. `subject / source / session / turn` identity 必须真实；未知身份不能启用 adjacency。
2. tenant、scope、permission、retention 与 revocation 不得泄漏。
3. Raw Evidence durable commit 与 Canonical single-writer authority 不变。
4. Reader-visible trace 必须精确等于真实序列化输入和 token ranges。
5. ordinary lookup 必须 grounded 且 relation-correct；strict COMPLETE 只有现有
   `DecisionEngine` 可以产生。
6. retrieval、Context、模型和 Lab 都不能直接修改 Canonical State。

通道选择、quota、RRF、Context policy 和模型后端都是可替换策略，不升级为新的权威对象。

## 5. 本 Goal 的范围

### 必须完成

- current-head isolated PostgreSQL、0048/0049、RLS/security/concurrency/worker 重验；
- 本地 `init → doctor → start → smoke → stop`；
- Python Client、MCP、OpenWorker 和 framework adapters 的结构化 identity 传播；
- authoritative identity 才能参与 same-session adjacency；
- `raw_retrieval_trace / admitted_evidence_trace / reader_visible_trace` 三层语义；
- whole-unit、rank-aware token admission；
- ordinary lookup 的 grounded answer-span/relation Binding；
- strict operator 只消费已验证 Binding，并由唯一 `DecisionEngine` 判断 COMPLETE；
- official Canonical/FTS/Dense 小 quota union、identity dedup/RRF 和 EvidenceSet selection；
- local golden flow、warm soak、failure degradation 与 package handoff；
- Product black-box build 供 Lab 做 Qwen/vLLM LongMemEval。

### 明确不做

- 新数据库 schema、新 Store、新微服务或第二套 Memory State；
- 自由搜索 Agent、模型 action ranking、多轮 refinding 或 graph authority；
- 自动 Formation promotion、durable Formation schema 或 profile default-on；
- 用关键词扩展解决 temporal COUNT completeness；
- 将 generative Reader 或 benchmark harness 复制进 Product；
- 为本 Goal 全面拆分 `retrieval.py` 或重写已有 acquisition/worker；
- public MCP schema、冻结 architecture/v1.0 或 formal holdout 变更。

## 6. 目标产品路径

### 写路径

```text
Host / Agent
→ typed Python client or MCP capture
→ authoritative speaker + source/session/turn context when available
→ Raw Evidence durable commit + Outbox
→ existing projection worker + lease heartbeat
→ FTS / optional Dense terminal
```

派生索引失败只能降低 recall，不能回滚或丢失已经提交的 Raw Evidence。

### 读路径

```text
query + subject + policy scope
→ current typed QueryIR / minimal task contract
→ Canonical exact + Raw FTS + optional Dense in one acquisition phase
→ per-channel small quota preservation
→ identity dedup + RRF
→ authoritative same-session adjacency only
→ hydration + live governance
→ grounded lookup Binding or strict typed Binding
→ requirement-role EvidenceSet selection
→ LookupReadiness or StrictSufficiency
→ atomic MemoryContext + exact reader-visible trace
→ Host Reader at most once, or deterministic result / explicit insufficiency
```

普通 recall 状态只需要：

```text
READY | AMBIGUOUS | INSUFFICIENT | DENIED
```

普通 recall 不声明 strict COMPLETE。COUNT、RATIO、STATE_DIFF、VERSION 或范围完备任务仍走严格
Binding/proof lane；未闭合时必须保持不充分，而不是继续生成关键词。

## 7. 五个执行阶段

### S0 — Fresh 产品纵向基线

目的：在新 Product 仓库证明现有纵向核心，而不是先改检索算法。

工作：

- 首次提交 Product baseline，生成 commit-addressed manifest；同步更新 Lab Product pin；
- 新建隔离 PostgreSQL，迁移到 `0049_namespace_cleanup_terminal_counts`；
- 使用 migration/API/Steward/worker/Audit 分离角色运行 RLS、安全、并发和 worker tests；
- 运行真实 `milai-ops init/doctor/start/smoke-test/stop`；
- MCP/OpenWorker 完成 capture/query/revoke smoke；
- 在慢 projection batch 下重验现有 heartbeat/lease renewal；只有复现缺陷时才修改实现；
- 完成后删除临时数据库，生产数据库 mutation 必须为 0。

退出门：

```text
fresh migration to 0049                         PASS
real-role RLS/security/concurrency              PASS
init/doctor/start/smoke/stop                     PASS
MCP/OpenWorker vertical smoke                    PASS
recoverable lease expiry / renewal              PASS
worker fatal exit                               0
terminal lease residue                          0
restart + idempotent replay                     PASS
production database mutation                    0
```

S0 通过后自动进入 S1。失败时先判断环境、配置或产品缺陷，修复通用根因并重跑受影响门，不重跑
全部历史实验。

### S1 — Identity 与可见证据真实性

目的：恢复产品输入语义和评测可归因性。

工作：

- 给 Python Client `EvidenceCaptureRequest` 增加向后兼容的 typed `speaker/source_context`；
- `AgentMemory`、MCP、OpenWorker、LangGraph 和 AutoGen 在拥有真实身份时原样传播，不猜测
  session ordinal；
- 复用现有 `EvidenceSourceContext` / `EvidenceSourceIdentity`，不建立第二套 identity 对象；
- `identity_source=UNKNOWN` 时禁止 adjacency 和语义效果评分；
- 修正 `CandidateEnvelope`、Evidence reference、Context grouping 的 session/turn 传播；
- 分离 raw retrieval、admitted Evidence 和实际 Reader-visible trace；
- whole-unit admission，禁止候选前缀截断后仍记为 Reader 已见；
- infrastructure failure 与 semantic insufficiency 使用不同 terminal class；
- 使用 exact tokenizer/chat template 计费。

先运行 24-case outcome-blind context preflight，不调用 Reader/Judge。

退出门：

```text
structured identity on capable captures         1.0
SessionIdentityIntegrity                         1.0
CrossSourceSessionAdjacencyExpansion             0
ReaderVisibleTraceExactness                      1.0
ContextSerializationReplayEquivalence            1.0
InfrastructureFailureAsSemanticAbstention        0
24-case context construction system failure      0
Reader/Judge calls                               0
```

通过后生成一个新的 untreated baseline identity，旧 R4 永不 resume。

### S2 — 简单且正确的 Recollection

目的：接通已有 acquisition 能力，只新增缺失的轻量 lookup/selection 语义。

工作：

- 复用现有 `compile_acquisition_plan`、Raw/Dense per-slot quota、RRF union 和
  `ReaderEvidencePlan`；
- Canonical exact 与 Raw FTS 始终可用，Dense 只在正式 projection/capability 可用时加入；
- 固定一次 acquisition phase，不调用策略模型；
- 将 Reference integrity 与 Semantic Binding 分开；
- ordinary lookup 校验 grounded span、subject、relation 和 source role，不要求完整 Event ontology；
- strict operator 校验 identity、unit、event time、dedup 和 proof obligation，只消费已验证 Binding；
- 用 requirement/evidence-role coverage 选择集合，而不是单一 global Top-k；
- 重放 DG25/DG27 的 known false Binding 和 Wrong COMPLETE fixtures；
- DG28 的 7 个机会只作为 manipulation check，不能作为效果证明。

若需要新代码，优先增加一个小的 `lookup_readiness` domain/application seam；不要复制
DecisionEngine，也不要整体重写 4,000 行 retrieval orchestration。

开发对比只保留：

```text
B0  repaired untreated Product baseline
B1  simple quota union + EvidenceSet + grounded Binding
```

退出门：

```text
AcceptedReferenceIntegrity                      1.0
asserted SemanticBindingPrecision               >= 0.95
known false relation accepted                   0
strict Wrong COMPLETE                           0
permission/revocation/Canonical read-path leak  0
DG28 opportunity admitted coverage              >= 6/7
model/provider policy calls                      0
automatic semantic retries                      0
```

若 B1 没有稳定 mediator gain，选择 B0 并继续 S3；不把整个 Product 判失败。

### S3 — Local-ready 产品体验

目的：让普通用户不理解内部 Evidence/Claim/UUID 也能完成记忆生命周期。

必须完成一条 golden flow：

```text
one local setup
→ “记住……”
→ Raw Evidence committed and searchable
→ Runtime/worker restart
→ new-session recall with inspectable source
→ explicit correction creates versioned state
→ current answer changes without erasing history
→ revoke/delete
→ later query excludes revoked memory
→ restart preserves expected state
```

验证 24 个产品场景和 100-request warm soak，覆盖中文/英文、单/多 session、assistant-answer、
Canonical current state、update、insufficient evidence、revocation、cross-scope、model outage、
projection lag、worker restart 和 no-memory-needed。

只整理本次触及的 code seam：显式 imports、identity adapter、lookup readiness、EvidenceSet selector
和 trace observer。其他 default-OFF 实验模块继续作为技术债，不在本阶段大规模删除。

退出门：

```text
golden flow                                    PASS
24-case product task success                   >= 0.90
100-request typed terminal rate                1.0
read-after-write searchable P95                <= 5 s
retrieval + Context P95                        <= 2 s
warm memory-control P95                        <= 500 ms
model outage deterministic fallback            1.0
scope/revocation/deletion leak                 0
Canonical mutation from read path              0
one feature flag restores repaired baseline    1.0
```

S3 通过即可形成 local-ready 结论，不等待 LongMemEval 500 或 Formation。真实个人数据仍需现有
encryption、backup/key recovery 和 deletion drill 单独通过。

### S4 — Lab 黑盒 LongMemEval 确认与交付

目的：在产品已可用后确认简单 recall treatment 的泛化，不让 benchmark 阻塞本地交付。

Product 只交付：

- commit-addressed manifest / wheel；
- public MCP、OpenWorker 或 typed client interface；
- exact trace 和 typed terminal；
- feature flag 与 rollback 配置。

LongMemEval harness、labels、Reader、Judge、结果和大型 artifacts 全部留在 MiLAi-Lab。

执行楼梯：

```text
24-case context/identity preflight
→ repaired untreated 128-case baseline
→ matched B0/B1 128-case effect
→ entry gate PASS
→ interleaved matched 500-case confirmation
```

500-case 进入门：

```text
Product manifest and Lab pin                    PASS
S0 isolated PostgreSQL/worker                   PASS
24-case identity/visibility                     PASS
128-case SystemContextSuccessRate               >= 0.98
systemic worker exit                            0
cross-session contamination                     0
ReaderVisibleTraceExactness                     1.0
strict Wrong COMPLETE on repaired slice         0
candidate feature default                       OFF
```

#### 固定测试合同

- 数据：LongMemEval-S cleaned 500，固定 case order；
- 两臂：repaired untreated Product baseline 与 simple candidate；
- Reader/Judge：本地 vLLM Qwen，固定 model revision、tokenizer、chat template 和 prompts；
- Answer 全部完成后才运行 Judge；Judge `temperature=0`、严格结构输出；
- Reader 与 Judge 若为同一 Qwen，明确披露 self-judge；不声称 GPT-4o leaderboard 等价；
- Evidence token budget 不使用任意 512/1024/2048 treatment；按
  `usable model context - fixed prompt - answer reserve - safety margin` 计算一次并冻结；
- 只装入完整 Evidence units，保存精确 token ranges；
- 两臂固定相同 candidate、hydration、action、token、timeout 与 retry ceilings；
- transport 或 schema failure 在健康检查后最多一次 technical retry；语义结果不重试、不投票。

并发采用三个独立池：PostgreSQL/context、Reader、Judge。先在 24/128 slice 测得稳定吞吐，再将
最终并发冻结在不触发 lease/显存/timeout 退化的最高值，最多 16；500 cases 按 case 交错执行
B0/B1，避免端点时间漂移。

主指标：

```text
SystemContextSuccessRate
official Session Recall@5 / NDCG@5
AllRequiredEvidenceGroupCoverage
ReaderVisibleGoldSpanCoverage
QwenJudgeAccuracy
strict Wrong COMPLETE
P50/P95 latency
```

Candidate admission：

```text
SystemContextSuccessRate                        >= 0.99
strict Wrong COMPLETE                           0
Evidence-group coverage delta                   >= +0.05 absolute
QwenJudgeAccuracy point delta                   >= +0.02
paired Judge 95% CI lower bound                 >= -0.01
P95 latency                                     <= 1.5x baseline
scope/revocation/wrong-relation leak             0
```

普通 QA 允许报告 paired win/loss，不再要求每一个 baseline-correct case 零变化；严格 operator、
权限、撤销、错误关系和 Wrong COMPLETE 仍保持零容忍。

## 8. 失败后的自动修复与继续

Goal 激活后按以下控制执行：

```text
for stage in S0..S4:
    run smallest valid gate
    while gate not met:
        classify one root cause
        record one compact issue
        repair the general cause
        run targeted positive + negative tests
        rerun only the affected gate
    continue to next stage automatically
```

具体规则：

- infrastructure、配置、transport 或 protocol failure：修复后继续当前阶段，不转成方法终态；
- 相同代码、数据、模型和配置下的瞬时 transport failure，可健康检查后技术重试一次；
- semantic failure：不得换 seed、改 case、增 Top-k 或重复调用；修改语义后生成 fresh outputs；
- optional treatment 无稳定增益：关闭该 treatment，选择更简单 baseline，继续产品交付；
- 同一根因完成三次实质通用修复仍重复：执行 design simplification，替换或删除该组件，不再
  叠加 validator/receipt/retry；
- 只有权限不明、可能破坏数据、需要 public API/schema 变更、缺少用户授权或不可替代外部依赖
  时暂停并请求用户；
- hard authority/scope/revocation breach：隔离当前临时环境，修复后以 fresh isolated DB 重放安全
  负控；除非需要破坏性恢复，不自动终止整个 Goal。

## 9. 高效开发与最小审计

### 开发测试阶梯

```text
edit
→ narrow unit/contract test
→ affected package lint/type/test
→ stage-end PostgreSQL or adapter gate
→ S4 前一次 full Product matrix
```

不在每个小修复后运行 599 tests 和六个 adapter 全矩阵。S0/S3/S4 才运行适用的完整门。

CPU 静态、unit、adapter build 可并行；PostgreSQL 使用相互隔离数据库；Reader 与 Judge 分阶段并发。
不以提高并发本身作为效果，不在 sealed run 中动态修改 concurrency。

### 最小制品

Product 开发只维护：

```text
one compact issue log
one stage acceptance summary
updated PRODUCT_CURRENT_STATUS.md
updated product.manifest.json at handoff
```

Lab benchmark 每个正式 run 最多：

```text
run.json
cases.jsonl
metrics.json
terminal.json
```

禁止：

- receipt-of-receipt、自引用 manifest 或每阶段四件套；
- 两个重复独立 witness；
- 每次修复复制整套源码 SHA；
- 首次失败即 PARK/terminal；
- case-specific synonym、regex、case ID 或 gold-aware rule；
- 为实验临时逻辑修改 frozen architecture 或建立新数据库对象。

## 10. 阶段流转与最终处置

| 结果 | 动作 |
| --- | --- |
| 当前阶段 PASS | 更新一次状态，自动进入下一阶段 |
| 可修复 failure | 修通用根因、窄测、重跑受影响门，然后继续 |
| Candidate 无增益 | 保持 flag OFF，选择 repaired baseline，继续交付 |
| vLLM/外部资源不可用 | S3 可形成 local-ready；S4 记为 benchmark pending |
| 需要新权限、Schema/API 或破坏性操作 | 暂停并请求用户授权 |

允许的产品结论：

```text
PASS_PRODUCT_LOCAL_USABILITY_KEEP_BASELINE_RECALL
PASS_PRODUCT_LOCAL_USABILITY_AND_SIMPLE_RECALL
PASS_PRODUCT_LOCAL_USABILITY_LONGMEMEVAL_CONFIRMED
PASS_PRODUCT_LOCAL_CORE_QUALITY_PENDING
BLOCKED_EXTERNAL_DEPENDENCY_OR_AUTHORITY
```

其中：

- H1 PASS、H2 无增益：选择 `KEEP_BASELINE_RECALL`，产品仍可本地交付；
- H1/H2 PASS、S4 尚未完成：`LOCAL_USABILITY_AND_SIMPLE_RECALL`；
- H1/H2 与 S4 PASS：`LONGMEMEVAL_CONFIRMED`；
- H1 未完成：保持 `ACTIVE_REPAIR_REQUIRED`，不是第一次失败就宣告整个 Goal 终止。

以上结论均不等于 production-ready、Schema freeze、public remote deployment、formal holdout
或真实个人数据资格。

## 11. Definition of Done

- [x] Product 已有独立 baseline commit，Lab pin 绑定 commit + manifest；
- [x] S0 fresh PostgreSQL、真实角色、operations、MCP/OpenWorker 和 lease 门通过；
- [x] S1 structured identity、same-session adjacency、三层 trace 和 exact packing 通过；
- [x] repaired untreated baseline 使用新 Context 重建，旧 R4 未 resume；
- [x] S2 ordinary relation Binding、strict COMPLETE owner 和 EvidenceSet selection 通过；
- [x] 已按效果选择 simple candidate，默认保持 OFF 且单 flag 可回退；
- [x] S3 local golden flow、24 scenarios、100 warm、restart/revoke/outage 通过；
- [x] 一次 full Runtime、六 adapters、architecture lock 和 clean builds 通过；
- [x] Product manifest 与 Lab pin 更新；
- [ ] 若 S4 进入，LongMemEval 使用本地 vLLM Qwen 且按 matched 预算完成；
- [ ] Formation、reranker、Planner、graph 和 multi-round refinding 未进入默认产品路径；
- [ ] public API、Schema 0.1.x 和 architecture/v1.0 未未经授权改变；
- [ ] `Schema = NO-GO FOR FREEZE` 与未完成发布门准确记录。

## 12. 激活后的前三项动作

1. 审阅并创建 MiLAi-Product 初始 baseline commit，重建 Product manifest，并让 Lab lock 绑定该
   commit；
2. 在 fresh isolated PostgreSQL 上执行 migration 0048/0049、真实角色和 worker/operations 纵向门；
3. 以 Python Client 结构化 `speaker/source_context` 传播为第一处窄改动，完成 identity/adjacency
   正反例，再开始新的 24-case context preflight。

最终原则：

> 先让 Product 能稳定记住、找回、解释来源、修正和忘记；再证明一个简单的多通道
> EvidenceSet 比修复后的 baseline 更好。失败后修通用原因并继续，无增益时删掉复杂度而不是
> 增加规则。
