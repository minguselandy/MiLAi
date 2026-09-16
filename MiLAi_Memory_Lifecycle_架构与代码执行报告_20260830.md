# MiLAi Memory Lifecycle：MILA-ML-MASTER@1.2→1.5 执行报告

> 日期：2026-08-30（Asia/Shanghai）  
> 执行权威：初始阶段 `MILA-ML-MASTER@1.2`；修复与后续开发后同步为 `MILA-ML-MASTER@1.6`  
> 架构基线：`MILA-ML-ARCH@1.0`  
> 审查状态：`INTERNAL_PROVISIONAL`  
> Formal holdout：未使用  
> Experimental feature flags：`OFF`

> 阅读说明：第 0–7 节保留 Master 1.2/1.3 当时的阶段性执行快照；当前状态以第 8–10 节和 `MILA-ML-MASTER@1.6` 为准。

## 0. 1.3 修复与后续开发摘要

1.2 的首轮负结果没有被当作项目终止点。本轮保留 DG-27 的负证据，同时按 first-loss 转向更简单的 deterministic Read Path 和 Raw-preserving Formation，完成如下开发：

| 工作 | 结果 | 主要证据 |
| --- | --- | --- |
| DG-27 旧问题修复 | V02 的 span/timezone 协议错误已修复；V03 有效 effect 仍有 Wrong COMPLETE/正确组回归 | `var/dg27/v03/attempt-004/terminal.json` |
| DG-28 Lite | deterministic lexical union 将 target candidates 4/7 提高到 7/7，bindings 3/7 提高到 6/7；precision 1.0，Wrong COMPLETE 0 | `var/dg28/lite/dg28-lite-lexical-union-20260830-001/receipt.json` |
| MF-03 identity/time | 24/24 event identity、4/4 entity identity、2/2 occurrence time；修复 multi-date span 被误当成唯一 anchor 的问题 | `var/mf03/mf03-formation-sidecar-20260830-004/receipt.json` |
| DG-28 formed consumption | 不改变 44 个 candidates，消费 1 个 Formation event 将 bindings 6/7 提高到 7/7 | `var/dg28/formation/dg28-formation-consumption-20260830-002/receipt.json` |
| MF-04 state/change | StateAssertion 6/6，StateTransition 3/3，precision/recall 均 1.0 | `var/mf04/mf04-state-change-formation-20260830-001/receipt.json` |
| EV-01 evolution bridge | 复用现有 Proposal→Steward→ClaimVersion/OpenIssue 路径；真实 PostgreSQL 完成 update、correction、revoke、blocked、reground replay | `var/ev01/ev01-governed-evolution-bridge-20260830-001/receipt.json` |
| DG-30 integration | 7/7 candidates 与 bindings，precision 1.0，Wrong COMPLETE 0，query-time model/refinding 均 0 | `var/dg30/terminal-v002.json` |
| MF-06 A/C descriptive | Raw+Simple 6/7 → Formed+Simple 7/7，ΔF=0.142857；仅净增 1 个义务且 exact paired bootstrap CI `[0, 0.428571]`，因此 ML-H1 未建立 | `var/mf06/mf06-ac-descriptive-20260830-001/receipt.json` |

两个实现级根因已做通用修复：

- 多日期句子不再被整句作为单一 temporal anchor；Runtime 只接受精确 clause anchor，否则返回 `TEMPORAL_ANCHOR_TIME_AMBIGUOUS`。
- 同一 span 内的多个 interpretation 不再互相借用实体词。存在 grounded entity projection 时以该 projection 为兼容性边界；仅在它为空时回退原 span。

Master 1.3 阶段没有为补齐编号强行实现 MF-02：当时的 4 个 episode obligations 全部是单 turn/全 span，不具备可识别的 split/merge 对照。因此先扩充 non-holdout Formation validation，而没有在简单记忆上继续叠加检索和分割规则。

## 1. 总结

本轮完整执行了 Master 1.2 明确授权的三个泳道，并在条件门处停止：

| 泳道 | 最终状态 | 关键结论 |
| --- | --- | --- |
| DG-27 V03 protocol recovery | `FAIL / WRONG_COMPLETE_REMAINS` | 有效 D0–D3 effect 已形成；D1 仍有 1 个 Wrong COMPLETE，D2/D3 丢失 11 个基线正确组；DG27-H1/H2 均不支持 |
| MF-01 S2–S4 passive audit | `PASS_FORMATION_FIRST_LOSS_LOCALIZED` | 125/125 义务完成唯一 first-loss 或 terminal-survival 归因；审计行为等价；MF01-H1/H2 均支持 |
| DG-28 S0/S1 acquisition preparation | `S0_S1_ACQUISITION_ONLY_PREPARED` | 7/7 目标在官方 channel union shadow 中有 candidate-level hit；因 DG27-H1 未通过，未进入 final effect |

在该 1.2 检查点尚未启动 DG-28 S2/S3、DG-29、DG-30、MF-02～MF-06、EV-01 或 formal holdout。当时没有改变 PostgreSQL schema、public MCP schema、`architecture/v1.0`、权限/撤销边界或 Canonical 写入路径。

## 2. DG-27：协议修复与有效 matched effect

### 2.1 V03 通用协议修复

V02 的模型 offset/timezone 失败被改造成离线 fixture，并实现以下 Runtime-owned materialization：

- 模型返回 source exact quote，不再计算 Unicode/Python offset；Runtime 对唯一 quote 推导 `[start,end)`。
- quote 缺失或不唯一只拒绝当前 hypothesis，处置为 `REJECTED_PROTOCOL`，不终止无关 hypothesis/candidate。
- 无 timezone 但 source observed time 提供明确 offset 时，Runtime 解析并记录 provenance。
- 无确定 timezone context 时，event time 降级为 `UNRESOLVED`，保留非时间语义并禁止 temporal Binding。
- 模型候选身份使用 request-scoped JSON object schema：候选 ID 是必需键且 `additionalProperties=false`。
- 明确无关候选使用 `IRRELEVANT` hypothesis；真正不可解释时仍允许零 hypotheses。

最终 adapter 仍保持：模型无 Evidence admission、AcceptedBinding、COMPLETE、Reader 或 Canonical authority；top-level parse、候选集合身份和 source mapping 损坏继续 batch-fatal。

### 2.2 Repair iteration 记录

Master 1.2 将 fail-closed 且无 state escape 的实现/协议错误定义为 `REPAIR_ITERATION`，不是 Goal terminal。本轮按该状态机保留了三次中间证据：

1. attempt-001：canary 一次通过；effect 前模型响应数组顺序变化，被旧实现误判为 identity drift。0 scorer / 0 state mutation。
2. attempt-002：允许精确双射集合重排；真实输出仍出现缺失/外来 candidate identity，继续 fail-closed。0 scorer / 0 state mutation。
3. attempt-003：改为 request-scoped exact candidate-key schema；canary 返回全部空 hypothesis set，未满足“至少一个合法 local disposition”，因此没有 run-lock/effect。该次还暴露并修复了 failed canary raw evidence 应先受限落盘的 runner 顺序。

attempt-004 使用相同模型、温度、top-p、candidate pool 与 validator，没有做结果导向的 top-k/seed sweep。新 canary 一次通过：8 个候选、8 个 `VALID` dispositions、0 retry、0 authority/canonical mutation；raw response 以 mode `0600` 受限保存并绑定 digest。

### 2.3 有效 D0–D3 effect

有效 effect 冻结并执行：

```text
queries                         10
requirements                    15
candidate occurrences          110
effect model calls              15
concurrency                      4
automatic retries                0
acquisition / Reader calls       0 / 0
canonical / authority violations 0 / 0
```

108 个 raw hypotheses 的 materialization 分布：

```text
VALID                         97
DOWNGRADED_UNRESOLVED          9
REJECTED_PROTOCOL              2
```

未评分输出先以 digest `de71bd42e8e2d663b3e4a0aa8a38db7fe4925e7e8cda2253525a12b77cc940b8` 封存，之后 scorer 才打开 gold registry 一次。

| Arm | Wrong COMPLETE | AcceptedBinding | Known false | Valid groups | Baseline correct groups lost |
| --- | ---: | ---: | ---: | ---: | ---: |
| D0 historical replay | 16 | historical | n/a | historical | n/a |
| D1 deterministic + boundary | 1 | 17 | 5 | 14 | 0 |
| D2 V03 N-best + boundary | 0 | 0 | 0 | 0 | 11 |
| D3 single-best reuse | 0 | 0 | 0 | 0 | 11 |

D1 未完全关闭已知 Wrong COMPLETE；D2/D3 虽然 fail-closed 到没有 false final Binding，但完全丢失可接受 Binding，形成严重 correct-case regression。这个结果是有效 treatment 负结果，不再作为协议 repair iteration。

终态：

```text
status       FAIL
reason_code  WRONG_COMPLETE_REMAINS
DG27-H1      NOT_SUPPORTED
DG27-H2      NOT_SUPPORTED
terminal     var/dg27/v03/attempt-004/terminal.json
```

因此 DG-28 final DecisionBoundary effect 的条件 entry 不成立。

## 3. MF-01：被动 Formation first-loss audit

### 3.1 Passive hook 与行为等价

新增 observer 只消费 sealed obligation 与冻结 stage availability，输出非权威 trace value；它不接入产品 control/data path，也不创建 Formation、Proposal 或 Canonical object。

行为等价 smoke 使用 identity passthrough，并重放旧 lock 绑定的 product/source 文件身份。以下全部 exact-match：

- Evidence envelope；
- Proposal output；
- Canonical state；
- retrieval projection；
- query output；
- 对象身份、值与 canonical digest；
- 冻结 product baseline 与 production code identities。

审计新增 Provider、embedding、Reader、database write 与 Canonical mutation 均为 0。

### 3.2 125 个义务的 first-loss

| First-loss / survival | Count |
| --- | ---: |
| F10 EPISODE_FORMED | 4 |
| F20 MENTION_FORMED | 28 |
| F30 IDENTITY_RESOLVED | 28 |
| F40 EVENT_TIME_GROUNDED | 2 |
| F50 STATE_OR_CHANGE_FORMED | 9 |
| F60 PROPOSAL_EMITTED | 4 |
| TERMINAL_SURVIVAL | 50 |
| Total | 125 |

`TERMINAL_SURVIVAL=50` 由 27 个 raw retrieval projection obligation 与 23 个 query-only、合法不进入 Canonical promotion 的 disposition 构成。4 个 synthetic governed-review disposition 因没有 Formation-generated proposal 在 F60 首损。

主要指标：

```text
ObligationAttributionCoverage  1.0
StageAvailabilityCoverage      1.0
ProvenanceClosureRate           1.0
BehaviorEquivalence             true
ProjectionRetention             1.0
IntroducedProviderCalls         0
CanonicalMutationsCausedByAudit 0
```

F10–F50 当前没有 formation-time artifact，因此对应 episode、mention、identity、event time、state assertion 与 transition retention 为 0。这是实际路径定位，不是在 MF-01 内模拟缺失能力或实现 treatment。

终态与后继路由：

```text
status   PASS_FORMATION_FIRST_LOSS_LOCALIZED
MF01-H1  SUPPORTED
MF01-H2  SUPPORTED

MF-03 identity/event/time  58
MF-04 state/proposal       13
MF-02 episode               4
```

该阶段 Master 不授权 MF-02/03/04，故当时路由只记录为 `RECORDED_NOT_STARTED_NOT_AUTHORIZED`。

## 4. DG-28：S0/S1 acquisition-only preparation

DG-28 只读取 DG-24 已由正式 `OfficialRetrievalAuditProbeExecutor` 产生并封存的 channel outputs，没有在本次 preparation 新增 retrieval call。冻结内容：

```text
target groups                    7
CHANNEL_ELIGIBLE_NOT_INVOKED     6
CHANNEL_CUTOFF_DROP              1
query × requirement              3
official channel outputs        15
historical occurrence lineage  272
identity-dedup union candidates 255
new official calls               0
```

| Case / requirement | Union candidates | Target groups with candidate hit |
| --- | ---: | ---: |
| `2e6d26dc / MATCHING_EVENTS_IN_RANGE` | 89 | 5/5 |
| `88432d0a / MATCHING_EVENTS_IN_RANGE` | 72 | 1/1 |
| `a82c026e / LOOKUP_ANSWER` | 94 | 1/1 |

每个唯一 Evidence ID 保留全部 channel、rank、score、occurrence、request、query 和 index lineage。union 后只做 identity dedup，没有 evaluator-owned BM25/Dense/fusion/filter。

7/7 candidate-level hit 只证明 acquisition opportunity 存在，不是合法 Binding、OperatorReady 或 COMPLETE。由于 DG27-H1=`NOT_SUPPORTED`：

```text
Gate executed             false
Binding executed          false
RequirementState derived  false
Sufficiency executed      false
Reader executed           false
COMPLETE asserted         false
results.json written      false
terminal.json written     false
```

DG-28 停在 `S0_S1_ACQUISITION_ONLY_PREPARED`，final effect 未授权。

## 5. 验证与制品

最终相关质量门：

```text
DG-27 targeted pytest / Ruff / mypy / direct Binding-Sufficiency  PASS
MF-01 targeted pytest / Ruff / mypy                              PASS
DG-28 targeted pytest / Ruff / mypy                              PASS
DG-27 artifact replay                                            valid=true
MF-01 artifact replay                                            valid=true
DG-28 preparation replay                                         valid=true
```

关键 digest：

| Artifact | Digest |
| --- | --- |
| DG-27 V03 final run-lock | `a3531218003245c3bf296169e3c474c7f5679b928d26504ac115baddd86b4872` |
| DG-27 results | `c558b496b86d0e53fcea855418343574f4e07f4147d896bf005326e426e97717` |
| DG-27 terminal | `94273ada7ecacdf293aa7e1f27966e7f363ecce01a86b475b09d97591942a948` |
| MF-01 trace SHA-256 | `8530554fe1edeb2561d6db94cdbbed03584b051a3ba284997332039340bda7f9` |
| MF-01 results | `a63810320f091831efe8626dae72976cb46f7ebe89771a9599e9098bb1ea83df` |
| MF-01 terminal | `7e333ded4be775a9b2f1e92902d45a4fb5dbec6f8ef0b866665b297c70071868` |
| DG-28 acquisition shadow | `0dacf5fc3a78b48c04a140915c19410416aea6ff42b3150a7cb8f1adafa6f656` |
| DG-28 preparation lock | `3c44b8a3def78d058749df1338e3fd85e4dae988759262230fd62a40c6134011` |

主要机器制品：

```text
var/dg27/v03/attempt-004/{run-lock,results,terminal}.json
var/dg27/v03/attempt-004/restricted/canary-raw-response.json
var/mf01/{trace.jsonl,results.json,terminal.json}
var/dg28/run-lock.json
```

## 6. 当前项目边界

1. DG-27 的协议已经能够形成完整、可评分的 effect，但当前 Decision Boundary treatment 未通过安全/回归硬门；不得把 D2 的“零 false Binding”解释为成功，因为它同时产生零 AcceptedBinding。
2. DG-28 已证明 7 个 opportunity 在 official acquisition union 中可到达 candidate 层，但没有安全的共同 final boundary，故不能报告 retrieval gain 或 COMPLETE gain。
3. 在 1.2 检查点，MF-01 确认最大结构性缺口集中于 F20/F30，其次是 F50/F10；该证据当时只决定后继研究路由，未自动授权 MF-02/03/04。
4. Raw Evidence、noncanonical Formation sidecar、governed Evolution 与 query-local Recollection 的架构边界保持不变。
5. 后续任何 DG-28 final effect、MF treatment、EV-01、durable schema 或 formal holdout 都需要新的显式执行授权。

## 7. 1.3 阶段验证

~~~text
Runtime unit + contract + DG/MF/EV targeted regression   572 passed
Ruff (all touched implementation/evaluation/test files) PASS
strict mypy (16 core/eval/script files + MF-06)          PASS
MF-03 / MF-04 / EV-01 artifact replay                   valid=true
DG-28 formed / DG-30 / MF-06 artifact replay            valid=true
Frozen architecture bundle validation                   PASS
Frozen architecture release lock ac16f3...55d0e         PASS
EV-01 real PostgreSQL governed integration               1 passed
temporary PostgreSQL database cleanup                    PASS
~~~

没有修改 PostgreSQL schema、public MCP schema、Provider/Reader 合同或 `architecture/v1.0`。Experimental feature flags 保持 OFF，formal holdout 未使用。DG-30 的 `release_ready=false` 保持不变：当前结果是开发集上的实现闭合，不是产品发布结论。

## 8. 1.4 MD-01：统一 Memory Formation Bundle 与 Semantic Episode

用户在原 design-only Goal 之后明确授权执行 MD-01。S0 在 scorer 实现前封存 10 个 non-holdout conversations、35 个 turns 与 16 个 expected episodes，覆盖 same-topic continuation、explicit/implicit topic shift、session change、time gap、pronoun continuation、assistant clarification 与 correction continuation。

实现新增：

- `SemanticEpisodeCandidateV01`：完整 Raw turn spans、参与角色、topic features、boundary reason、timezone-aware source range、digest 与 noncanonical hard fields；
- `MemoryFormationBundleV01`：统一 episode、MF-03 semantic sidecar、MF-04 state/change sidecar、source snapshot/watermark 与强制 Raw fallback；
- `MemoryFormationReceiptV01`：绑定 bundle、sub-sidecar digests、Evidence IDs、episode digests 与零外部调用计数；
- `MemoryFormationBundleService`：query-independent 单次构造，只把 user Evidence 送入 semantic/state formation，assistant Evidence 仅保留为 episode context。

正式结果：

```text
status                         PASS_MD01_MEMORY_FORMATION_CORE
RawSpanCoverage                1.0  (1457/1457 chars)
EpisodeBoundaryPrecision       1.0  (6 TP / 0 FP)
EpisodeBoundaryRecall          1.0  (6 TP / 0 FN)
EpisodeBoundaryReasonAccuracy  1.0
EpisodePairwiseF1              1.0  (25 TP / 0 FP / 0 FN)
UserSemanticSourcePrecision    1.0
ArtifactLineageClosure         1.0  (31/31)
DeterministicReplay            1.0
Provider/Reader/Retrieval/DB   0/0/0/0
Canonical mutations            0
MF-03/MF-04 regression         0  (20 passed)
```

机器制品：

```text
var/md01/md01-memory-formation-bundle-20260830-001/
  run-lock.json
  results.json
  terminal.json
  receipt.json
```

关键身份：

| Artifact | SHA-256 / embedded digest |
| --- | --- |
| label fixture | `4877637b0954f59a618ea64dd73996f8b35b558fca49c0b9c048728d90623c97` |
| run-lock file | `57942a82b4164d82be182545339a29ead515a06986ecd3eae9589e385650f5a0` |
| results file | `4cec3ded2e8fdbefe58820387047671dbf2ebf54466b05a8c2250cba652cdae0` |
| terminal digest | `46392792cdc21267771060c4a23a9f9b9ccc16794a4722a9c8658c4738a629b2` |
| receipt digest | `3d17a07e39c97a5c338ed514cef57fd8a15c1dbe4c0cae090bc2487079fc4842` |

边界保持：没有 Migration、PostgreSQL/public MCP、background worker、Provider/Reader、Canonical state 或默认 feature flag 变化。MD01-H1/H2 仅在封存的首个 non-holdout validation 上支持；该结果不等于 MF-02 四臂 comparative effect、formal holdout、产品集成或普遍泛化。

## 9. 1.5 MF-02：Semantic Episode 四臂表示与独立泛化

用户在 MF-02 design-only Goal 之后明确授权执行。本次在 scorer 实现前分别封存了 8-conversation repair-dev 和 24-conversation / 96-turn / 24-probe sealed-validation；sealed set 的 8 个预注册反例族各有 3 个 conversation，每个 conversation 同时含 same-episode 和 cross-episode pair。

实现包括：

- query-independent 的 `A_TURN / B_FIXED_WINDOW_2 / C_SESSION / D_SEMANTIC_EPISODE` 四臂 builder，各臂中每个 Raw turn 恰好出现一次；
- 本地确定性 Raw FTS，每个 probe 恰好一次，四臂共用已冻结 anchor ranking；
- Raw-turn ceilings `1..8` 下的 atomic-unit hydration，不截断 representation unit；
- conversation-macro direct/read scorer、paired bootstrap CI、失败分布与 Raw/role/lineage/scope 硬门。

repair-dev 首轮诊断暴露 1 个 over-split 和 7 个 over-merge。唯一通用 builder 修复只使用 repair-dev：assistant question-answer continuity 先于 time-gap 判定，取消无条件 pronoun continuation，并收紧词汇重叠的 semantic-related 门。此后执行了唯一次 protocol-valid sealed effect，未依据 sealed labels 回调规则。

正式结果：

```text
status                                  PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION
MF02-H1 / MF02-H2                       SUPPORTED / SUPPORTED

EpisodePairwiseF1 A/B/C/D               0 / 0.4 / 0.666667 / 0.958333
D direct delta vs C_SESSION              0.291667
direct paired bootstrap 95% CI           [0.250000, 0.333333]
D boundary precision / recall            1.0 / 0.875

SupportClosureAUC A/B/C/D                0.635417 / 0.625 / 0.625 / 0.734375
D read delta vs A_TURN                   0.098958
read paired bootstrap 95% CI             [0.078125, 0.114583]
D distractor rate delta vs A_TURN        -0.097222
Raw FTS calls / probes                   24 / 24
```

封存失败分布是 3 个 over-merge/topic-shift errors：`sealed-uncued-meeting`、`sealed-assistant-medical-records`、`sealed-multiple-bicycle-library`。over-split、assistant contamination 和 time-gap error 均为 0。它们保留在 terminal 中，未用 PASS 结论遮蔽。

安全与边界：Raw coverage、source order、user semantic source precision、lineage closure 和 deterministic replay 全为 `1.0`；database/Provider/Reader/retrieval/model call 和 Canonical mutation 全为 0；formal holdout 未使用，feature flags 保持 `OFF`。因此该结论只是 sealed non-holdout representation generalization，不是产品 retrieval recall、release-ready 或 formal-holdout 结论。

机器制品：

```text
var/mf02/mf02-semantic-episode-four-arm-20260830-001/
  run-lock.json  4b0d4eb8a3aeafae78345ddcaa8fc45c69f992b7f606ee79ac12e5682a065605
  results.json   dec3102942c474aff2b88692c6d8b1e8daf14d094b32fb25296caeb10ac8b3f3
  terminal.json  7aca3f2fdf689938b6e8879ed0db324c35032fd218117ec1c6e9eb154c730e8d
  receipt.json   0099fdf7bae0a30edafb3b09cf49ac215a23b7c3d325991156ea1a8e76f09949
```

最终实现身份被 terminal 绑定，artifact validator 为 `valid=true`。正式运行内嵌回归为 `32 passed`，全量 Runtime unit 为 `549 passed`，严格 mypy 和编辑文件 Ruff 均通过。下一路由是另行授权的 semantic episode product-shadow 设计或更大 identity/time/state-change validation；不继续在当前 24-case sealed set 上调规则。

## 10. 1.6 MD-02：Semantic Episode 边界鲁棒性与 Product Shadow

用户在 MD-02 design-only Goal 后明确授权执行。scorer、V02 与 shadow hook 创建前，先封存 8-conversation repair-dev、24-conversation / 96-turn / 24-probe 新 validation、六类 freshness contract 与 run-lock。V01 builder 和 official acquisition/query/context 路径身份一并冻结，MF-02 sealed set 仅允许事后历史 replay。

实现包括：

- noncanonical、query-independent 的 `BoundaryEvidenceV02` 与单独的 `MemoryFormationBundleServiceV02`，不修改冻结 V01；
- typed `SemanticEpisodeShadowObservationV01` 与 internal default-OFF hook；
- pre-query 完整 snapshot build，query-time 只复用 official Raw anchors；
- official `EvidenceAcquisitionExecutor → Binding → RequirementState → Sufficiency → Operator → MemoryContextCompiler` baseline digest；shadow 不回流任何正式决策对象；
- source snapshot/Evidence IDs/watermark/permission/retention/revocation 核对与 Raw fallback；
- conversation-level bootstrap、boundary/read 指标、行为等价、安全与成本审计。

repair-dev 首轮显示 V02 的 over-split 增量为 `0.25`。唯一通用修复是把相邻 assistant follow-up question 作为 dialogue-pair continuity，同时保留“assistant 问句不能无条件吞并后续 user turn”的严格规则；修复后 repair-dev over-split 增量为 0。该修复登记在 `repair-log.jsonl`，未读取 sealed score 调规则。

正式一次性结果：

```text
status                                  PASS_MD02_SHADOW_EQUIVALENT_BOUNDARY_UNRESOLVED
MD02-H1 / MD02-H2                       MISS / PASS

Boundary V01 → V02
OverMergePairRate                       0.916667 → 0
absolute reduction                      0.916667
paired bootstrap 95% CI                 [0.791667, 1.0]
OverSplitPairRate increase              0.027778  (gate <= 0.02, MISS)
EpisodePairwiseF1                       0.611111 → 0.979167
SupportClosureAUC                       0.645833 → 0.822917

Product shadow
baseline identity / build / replay      1.0 / 1.0 / 1.0
fresh / stale / ineligible / fallback   1.0 / 1.0 / 1.0 / 1.0
revocation / permission leaks           0 / 0
extra acquisition / Reader / Provider
  / model / DB write / Canonical        0 / 0 / 0 / 0 / 0 / 0
```

唯一 sealed boundary failure 是 `sealed-soup-broth` 的 over-split。该单例使 conversation-macro 增量越过硬门，因此 H1 不得判 PASS，也不允许依据该 case 回调 V02。MF-02 historical replay 不进入主分母且不用于规则变化；终态路由为 `KEEP_SHADOW_CONTRACT_REJECT_V02_BOUNDARY_POLICY`。

shadow 六类场景共产生 `OBSERVED=24`、`STALE_REJECTED=24`、`PERMISSION_REJECTED=72`、`RAW_FALLBACK=24`。描述性成本为 bundle build wall mean `8.792 ms`、CPU/turn `2.199 ms`、memory high-water `120682 bytes`、shadow overhead P50/P95 `0.339/0.399 ms`；本 Goal 未预注册 latency SLA。

机器制品：

```text
var/md02/md02-boundary-product-shadow-20260830-001/
  run-lock.json    d2cee4f689c9066a7afd4649e3d6b8c4a0213b83f958fdd3bb6054e72900f0e1
  results.json     3761d522c2e343222e0321fd22ca2131e32a06f4d1ac0bb6d34855db0b4640f4
  terminal.json    8b25edec280f52bf6cea6d8824fb26bfab948cdd50ef1ec4601c3f14c3039cd7
  repair-log.jsonl 69762dfe9c5d81ecb6f4b05dbdfe20f4220843ddd4af6cd4d8871a6fdb45060a
```

terminal embedded digest 为 `bc19c30db84d46420e9a2a6e73bbc945a7e3718e9df47fcef250f57951984af7`，validator 为 `valid=true`。正式运行内嵌回归 `44 passed`，全量 Runtime unit `556 passed`，post-effect artifact/contract tests `15 passed`，严格 mypy/Ruff 与独立 `WITNESS 2 6 0` 环境见证均通过。

边界保持：没有 formal holdout、GPU、模型、Provider、Reader、数据库、Migration、public MCP、background worker、durable Episode、Canonical mutation 或默认 feature flag 变化。H2 PASS 只支持保留 typed observation-only shadow contract；它不授权启用 shadow、更不授权 V02、产品 release 或 formal holdout。
