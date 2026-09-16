---
document_id: MILA-ML-MASTER
version: "2.1"
status: ACTIVE_EXECUTION_MASTER
normative_scope: execution_order_and_program_gates
architecture_baseline: MILA-ML-ARCH@1.0
development_control: MVP01_U0_WARM_002_FAILURE_REPAIR
active_goal: MILA-MVP-01@0.1
active_block: MILA-MVP-U0
execution_authorized: true
execution_scope: U0_WARM_002_FAILURE_REPAIR_PROBE
active_case_scope: MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE
active_run_scope: MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE
active_run_lock: var/mvp01/mvp01-u0-warm-repair-probe-20260901-002/run-lock.json
authorized_synthetic_query_class_count: 10
formal_warm_successor_authorized: false
authorized_benchmark_case_count: 0
selection_metadata_access_authorized: false
benchmark_case_execution_authorized: false
reader_answer_judge_calls_authorized: false
formal_holdout_authorized: false
standing_user_execution_authority: MVP01_U0_THROUGH_U3_SEQUENTIAL_NO_RECONFIRMATION
standing_user_execution_authorized_at: "2026-09-01T11:11:55+08:00"
latest_block_artifact: var/mvp01/mvp01-u0-warm-20260901-002/terminal.json
latest_block_artifact_sha256: 51e4961de03514d9fe3d79c9c653f6ef49d93849c6bce30a0f1ae63ab4741db0
latest_block_status: FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED
latest_block_results_sha256: fb8958447c681d1cd80cd8f35085a831d4488804cca99e6b7b47196b077afc1d
latest_block_checkpoint_sha256: 31b37c8980932f822673c1b4672efccbc01bffe137a93b89b42cba23f0e38c18
latest_block_run_lock_sha256: de720a2f713e944fdb64a5c73a155ff63bd1353ad7d53fa3369415fdb75cd301
latest_block_audit_status: NO_GO_SUCCESSOR_REPAIR_REQUIRED
latest_passed_block_artifact: var/mvp01/mvp01-u0-20260901-017/terminal.json
latest_passed_block_artifact_sha256: ba9fedb8ce69c82a927bc57620302391d52dfaaa1f4dd8c54383f610cf79f38a
latest_passed_block_status: PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY
latest_repair_probe_artifact: var/mvp01/mvp01-u0-warm-repair-probe-20260901-001/terminal.json
latest_repair_probe_artifact_sha256: a4b8331d0666824407693a44de9349e69750c5628691169e6e0022505266f775
latest_repair_probe_status: PASS_MVP01_U0_WARM_REPAIR_PRODUCTION_PATH_PROBE
next_authority_required: INDEPENDENT_AUDITOR_GO_AFTER_10_CLASS_REPAIR_PROBE
supersedes_execution_clauses:
  - DG-26-30-MASTER@1.0
  - MILA-ML-R02@0.2::unexecuted_future_navigation_only
---

# MiLAi Memory Lifecycle 总 Goal

> 日期：2026-08-30（Asia/Shanghai）  
> 冻结上位规范：`architecture/v1.0` / MiLAi Logical Architecture 1.0.0  
> 项目架构：[MILA-ML-ARCH@1.0](./MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md)  
> ExperimentalFeatureFlagsDefault：`OFF`  
> Formal holdout：未授权、不得使用

---

# 1. 唯一规范链与总目标

本文件是当前唯一的执行顺序、Program gate 和 terminal decision 来源。

~~~text
architecture/v1.0 + frozen Logical Architecture
  ↓
MiLA Lean V1 implementation contracts
  ↓
MILA-ML-ARCH@1.0                  stable Program / Plane baseline
  ↓
MILA-ML-MASTER@2.1                execution order / gates / terminal
  ↓
Program and local Goal contracts
  ↓
historical DG method documents
~~~

旧 `DG-26-30-MASTER@1.0` 只保留历史事实与 Program C 局部设计来源，不再控制项目级顺序、DG-28 是否包含模型、DG-30 声明范围或 Formation/Evolution entry gate。

总目标是在保留 Raw Evidence 的前提下，验证一条可归因的文本个人记忆生命周期：

~~~text
Raw Evidence
  ├─ Raw projection ───────────────────┐
  ├─ Formation → Formed projection ────┼→ Recollection → Typed completion
  └─ governed proposal → Evolution → Canonical projection ─┘
~~~

核心原则：

> 不用复杂检索补偿尚未形成的记忆，也不用有损结构化替代原始 Evidence。

Phase 1 仅含 user-assistant 文本交互中的个人事实、偏好、事件、状态变化、修正和撤销。多模态、procedural skill、agent trajectory gotcha 与 workflow learning 不进入本轮研究假设；LongMemEval-V2 仅作后续扩展候选。

---

# 2. 当前机器事实

本节只引用 terminal / run-lock；`NOT_RECORDED_IN_TERMINAL` 不使用当前 HEAD 回填历史身份。

| Goal | Authority artifact | SHA-256 | Code identity | Data / snapshot identity | As-of |
| --- | --- | --- | --- | --- | --- |
| DG-24 | `var/dg24/s8/dg24-s8-terminal-20260829-003/receipt.json` | `fff0f5ce8ab7b230c49923308f37c080d1eab58776d298a075cda513790a6aa0` | `NOT_RECORDED_IN_TERMINAL` | scorer-registry snapshot `4a88cb030e67cce456b1dfe159fce177a5ace4b972f11af2a6674639c52dc876` | `NOT_RECORDED_IN_TERMINAL`（run-id date 2026-08-29） |
| DG-25 | `var/dg25/terminal/dg25-s10-terminal-20260830-001/receipt.json` | `d2b660499fee9e8a1db79603aaedc96c361099a9ab00a1b959069965d80bd2a0` | `NOT_RECORDED_IN_TERMINAL` | associated frozen input `7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412` | `NOT_RECORDED_IN_TERMINAL`（run-id date 2026-08-30） |
| DG-26 | `var/dg26/terminal.json` | `72a98dda4a7bf202fa12ac8c18c1322e33e6f47c05e914db00992fc0596c6282` | run-lock commit `651099ba8cffc2675961bb9250ba44c158efccb5` | frozen input `7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412` | `2026-08-30T03:00:45.447408+00:00` |
| DG-27 V02 | `var/dg27/v02/terminal.json` | `cc010fa788d5671179cb7f076b85468f9803cfd42ad3d17287c95839546cd477` | run `dg27-v02-decision-boundary-20260830-001` / terminal digest `4ee94616d58d8758213775fe6a615b74a0831a91b9a466863856445ee2f64f33` | same frozen input | `2026-08-30T06:18:59.937172+00:00` |
| MF-01 S0–S1 | `var/mf01/run-lock.json` | `df86fac939d8033d3bd97a1add75b527b425080498242ab17510031a61c3a9d1` | lock digest `439069e1ef957802d5b191598067f832218a8152370957fa3487ef4f1672d4f2` | label seal `c2aa1d048fb0da87d6cce79ef4753f3ddf5d4eae5510bd2f6f0a215fa12717a8` | `2026-08-30T06:16:45.551384+00:00` |
| DG-27 V03 | `var/dg27/v03/attempt-004/terminal.json` | `ce5cb7966834cebd59757b8496f6ed2a011c31f07860ab827c164eb7f2b4249a` | terminal digest `94273ada7ecacdf293aa7e1f27966e7f363ecce01a86b475b09d97591942a948` | same frozen development input | `2026-08-30 15:17:21 +08:00` |
| MF-01 terminal | `var/mf01/terminal.json` | `28bf0cd16d41c3a6f33bc39ce1467b99bc26b74f867a36d1a25bda291d13cf74` | terminal digest `7e333ded4be775a9b2f1e92902d45a4fb5dbec6f8ef0b866665b297c70071868` | 14 cases / 125 sealed obligations | `2026-08-30 15:25:43 +08:00` |
| DG-28 Lite | `var/dg28/lite/dg28-lite-lexical-union-20260830-001/receipt.json` | `e9a60a17bf28232ec37ee57dde9a6420623d8d4d9e3e98baa3bb7c7d60776c2b` | receipt digest `18de654cc7af0d32c6b1451d5429c13f7a714e0f219539eda312420bda4ff8de` | 7 fixed opportunity groups | `2026-08-30 16:18:33 +08:00` |
| MF-03 | `var/mf03/mf03-formation-sidecar-20260830-004/receipt.json` | `b305fc71cca5ae9acda7be0b58e3deb89a6aa874c7b76f962bd7c091e60af7d4` | receipt digest `35c19d3df9ed3872f946c30fd1beaed4b800282398d53e10f7c0bd35e5d48f2d` | MF-01 sealed formation labels | `2026-08-30 17:06:32 +08:00` |
| DG-28 Formed | `var/dg28/formation/dg28-formation-consumption-20260830-002/receipt.json` | `9ebe44b49dc3354bbd3a1f8d094e6c00c2f079cf178668b96b9b7b2f410a05f5` | receipt digest `f82f67182fdd65bdcf7a620814eddbdadf43ad7281cb9a17ed5f3e358e24dc35` | identical 7-group candidate pool | `2026-08-30 17:07:35 +08:00` |
| MF-04 | `var/mf04/mf04-state-change-formation-20260830-001/receipt.json` | `e33baf7af901d7707176d12633c8320b501d77a7f9f849c3bd194da963fa37d3` | receipt digest `00e1748b762c44c8f9770e70718fa1d7443017cf2a4002c6793374cb01826022` | MF-01 sealed state/change labels | `2026-08-30 17:11:24 +08:00` |
| EV-01 | `var/ev01/ev01-governed-evolution-bridge-20260830-001/receipt.json` | `82803500dc6820ff80fa70d2343afa1095dc010e65714c7a23befea414db0932` | receipt digest `98bc8730804328ac27ff621f4c45f7426864239c448827d3186568105ae4c7ee` | real PostgreSQL governed replay | `2026-08-30 17:19:02 +08:00` |
| DG-30 | `var/dg30/terminal-v002.json` | `3950158c9fb23151412c0548c8a121a686f1c61a6462bd40edbfc45c7ab13634` | terminal digest `6fa2b04947b3a5c627f776f64b530b253fc863bbc56dcea920c7d746080a68c2` | read-path integration snapshot | `2026-08-30 17:08:00 +08:00` |
| MF-06 descriptive A/C | `var/mf06/mf06-ac-descriptive-20260830-001/receipt.json` | `a9c86b826f59dcc17a6fdc1140b08fc73767cc9794ffd8acedf244673dc53ea1` | receipt digest `b5cc76a32085b5258a803acc04813b4e1d063d75680ffa1f38827999bc47d064` | same 7 fixed obligations; no holdout | `2026-08-30` |
| MD-01 | `var/md01/md01-memory-formation-bundle-20260830-001/terminal.json` | `b54ad9d10ee4bca164a6da0ed0e832ceb174805424dd3a82bdac2130d922aee4` | terminal digest `46392792cdc21267771060c4a23a9f9b9ccc16794a4722a9c8658c4738a629b2` | 10 sealed contrasting conversations / 35 turns / 16 episodes | `2026-08-30T10:22:59.469453+00:00` |
| MF-02 | `var/mf02/mf02-semantic-episode-four-arm-20260830-001/terminal.json` | `7aca3f2fdf689938b6e8879ed0db324c35032fd218117ec1c6e9eb154c730e8d` | terminal digest `cf306e4830d7e0687e081ff01982cd6a4eced9ed15ae1b75fa6767c55ae0a6a0` | 24 sealed non-holdout conversations / 96 turns / 24 probes | `2026-08-30T12:46:06.716151+00:00` |
| MD-02 | `var/md02/md02-boundary-product-shadow-20260830-001/terminal.json` | `8b25edec280f52bf6cea6d8824fb26bfab948cdd50ef1ec4601c3f14c3039cd7` | terminal digest `bc19c30db84d46420e9a2a6e73bbc945a7e3718e9df47fcef250f57951984af7` | 24 new sealed conversations / 96 turns / 24 probes + six freshness scenarios | `2026-08-30T13:48:54.189209+00:00` |
| ML-CLOSURE | `var/ml_closure/ml-closure-20260830-001/lifecycle-terminal.json` | `b8d47201b33fbf52eb918e8b73f0951aa498ba463e61716dac7abea22f7e07ca` | terminal `PARKED_ML_CLOSURE_LONGMEMEVAL_BELOW_TARGET` | 500-case public run；Candidate 477 context failures，Formation applied 0 | `2026-08-31` |
| ML-R01 R4 checkpoint | `var/ml_repair/ml-r01-20260831-001/checkpoints/r4/context-seal-8.json` | `fa0f9faa3a8525589fc7e22828ccfda21fd57a9ef99156739f0a2e28a2460a3d` | explicit user-limited checkpoint；32/32 contexts PASS；cleanup/resource seal FAIL closed | Formation applied 0；answers/judges 0；formal holdout 未消费 | `2026-08-31T14:36:09+08:00` |
| ML-R02 terminal | `var/ml_r02/ml-r02-20260831-004/terminal.json` | `6b713fa26a8d3bf70f4836c651ffe97719272034b38763b9e884d0e28ae88e2b` | `COMPLETE_USER_LIMIT_8X4`；results digest `d6e89f01ce26bc784134368ba67b88a074f7c3815838096ae866d93fa7df4998` | 8 cases × 4 arms；32/32 Context/Answer/Judge/Score；128/500/formal holdout 未启动 | `2026-08-31` |
| GDPM-01 handoff | `var/gdpm/gdpm-b0-20260901-003/terminal.json` | `bcb6382d3a2b29e6b5712a2a2bbaa4d631a764d5d442e67f70a2e29449b41d78` | 24-case context-only terminal：4/24 PASS、20/24 repair-required | 14 个缺 ContextReceipt、6 个 MCP output-limit；Reader/Answer/Judge `0`；未执行复杂分支保持 OFF | `2026-09-01T09:34:02+08:00` |
| MVP-01 active | `var/mvp01/mvp01-u0-warm-20260901-002/terminal.json` | `51e4961de03514d9fe3d79c9c653f6ef49d93849c6bce30a0f1ae63ab4741db0` | 第二次 warm terminal 不可变 FAIL：100 requests / 100 logical attempts / 1 Runtime attempt / 90 archives；独立审计分层为 50 evaluator false failure、30 typed semantic-abstention outcomes（Bicycle 子集另有 receipt losslessness defect）、10 valid safe-empty terminals that miss the positive fixture expectation、10 real Atlas window-count contract failures；Reader/Answer/Judge 0，holdout 未消费 | `002` 不重放、不覆盖、不回填 PASS；只授权 fresh 10-class synthetic repair probe，formal successor 保持 NO-GO | `2026-09-01` |

DG-27 V02 是不可改写的运行事实，但它证明的是 fail-closed 验证生效，不是 DG27-H1/H2 失败：首个模型响应因 span offset 与 timezone 协议不合法而在 matched effect 前被 Runtime 拒绝。无 acquisition、Reader、Canonical mutation、authority violation 或 formal holdout 消耗。

| Goal | 机器结论 | 本 Master 处置 |
| --- | --- | --- |
| DG-24 | 6 个 channel 未调用、1 个 cutoff、3 个无现有通道发现；2 个 temporal proof gap | Program C diagnosis 基线 |
| DG-25 | 候选机会存在，但 Binding precision 与 Wrong COMPLETE 不允许采用 | 不采用候选策略 |
| DG-26 | fixed-pool StateView 无独立增益且有回归 | 保持 terminal，不重开 |
| DG-27 V02/V03 | V02 协议失败已修复；V03 有效 effect 仍有 Wrong COMPLETE/回归 | 保留负结果；不再用模型解释器作共同安全边界 |
| DG-28 Lite | `PASS_DG28_LITE_RETRIEVAL_GAIN`；Binding 3/7 → 6/7，precision 1.0，Wrong COMPLETE 0 | 采用最小 deterministic lexical union 作 Simple Raw arm |
| DG-29 | 未进入 | Formed+Simple 已闭合 7/7，`NOT_ENTERED_NO_REFINDING_OPPORTUNITY` |
| DG-30 | `PASS_READ_PATH_INTEGRATION`，但 `release_ready=false` | 封存 Read Path；不声称产品或 formal-holdout ready |
| MF-01 | `PASS_FORMATION_FIRST_LOSS_LOCALIZED` | 已完成路由 |
| MF-02 | `PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION`；D 直接 F1 `0.958333`，较最强简单臂增加 `0.291667`；D 读取 AUC `0.734375`，增加 `0.098958` | H1/H2 在 24-case sealed non-holdout validation 上支持；仅允许另行授权 product-shadow 设计，不是 formal holdout 或 release 结论 |
| MD-02 | `PASS_MD02_SHADOW_EQUIVALENT_BOUNDARY_UNRESOLVED`；over-merge `0.916667→0`，但 over-split 增量 `0.027778>0.02`；official shadow 全部 equivalence/freshness 门通过 | H1 MISS / H2 PASS；保留 default-OFF observation contract，拒绝当前 V02 boundary policy，不授权产品采用 |
| MF-03 | `PASS_MF03_FORMATION_IDENTITY_TIME`；24/24 events，2/2 event time | 作 Formed projection 输入 |
| MF-04 | `PASS_MF04_STATE_CHANGE_FORMATION`；assertion 6/6，transition 3/3 | 进入 EV-01 |
| EV-01 | `PASS_EV01_GOVERNED_EVOLUTION_BRIDGE`；6 个 hard gate 全 0 | 继续复用唯一 Canonical 写路径 |
| MF-06 A/C descriptive | Raw+Simple 6/7，Formed+Simple 7/7，ΔF=1/7，候选池不变 | 工程增益成立；仅 1 个净义务且 CI 含 0，ML-H1 未建立 |
| MD-01 | 统一 bundle 在 10 个封存 non-holdout conversations 上 Raw/role/lineage/replay 与 episode boundary/pairwise 指标全为 1.0；外部调用和 Canonical mutation 为 0 | `PASS_MD01_MEMORY_FORMATION_CORE`；作为 Program A sidecar substrate 和 MF-02 scorer sanity 前置，产品集成门仍未授权 |
| ML-CLOSURE | LongMemEval 端到端结果被 lease/worker failure 主导；Candidate `formation_applied=0` | 保留产品失败分数，不作 Formation 语义结论；由 ML-R01 接管修复 |
| ML-R01 | R4 user-limited checkpoint 已封存；32/32 contexts 成功，R/F snapshot identity 8/8；一个 cleanup witness 超时，Formation applied 0 | 保留为 predecessor 事实，不重跑或覆盖；semantic context 与 cleanup operational window 分栏 |
| ML-R02 | `COMPLETE_USER_LIMIT_8X4` | 封存全部历史 cells；未执行未来导航由 GDPM-01 接管，不 resume、不覆盖 |
| GDPM-01 | B0 24-case context-only 已封存为 `FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED`；4/24 PASS，14 个缺 ContextReceipt，6 个 MCP output-limit | 活动写权已移交 MVP-01；未执行的复杂分支不迁移，Reader/Answer/Judge 与 formal holdout 消耗均为 0 |
| MVP-01 | U0 receipt/wire 修复与 24-case context-only 已由 `017` 以 24/24 PASS 封存；warm-001 与 warm-002 均已不可变 FAIL | `002` 的资源与 SHA 链完整，但 evaluator false failure、typed semantic outcome、fixture expectation miss 与 protocol/receipt defect 被错误混算；当前只授权 fresh 10-class repair probe，formal successor、benchmark 与 Reader/Answer/Judge 均为 0 |

---

# 3. 不可变边界与统一术语

1. Raw Evidence 在 retention/revocation 允许范围内保留；合法删除不计为丢失。
2. Formation 输出是 noncanonical、versioned、provenance-linked、rebuildable 的 `FormationArtifactCandidate`。
3. Canonical 变化只经 `OperationProposal → Validator/StewardDecision → ClaimVersion/OpenIssue`。
4. 模型、EvidenceCandidate、Context 和 Reader 不能直接改写 Hard State 或宣布 canonical truth / COMPLETE。
5. access、revocation、tenant/scope 与 Evidence lineage 不得为 recall 放宽。
6. Formed projection 过期或未覆盖最新 Evidence 时必须标记 `PARTIAL/STALE`，保留 Raw fallback，且不得承担 completeness proof。
7. 新 durable logical object 必须走 architecture-vNext ADR；本轮不修改 `architecture/v1.0`。

统一术语：

~~~text
ExperimentalFeatureFlagsDefault = OFF
EvidenceCandidate               query-time retrieval object
FormationArtifactCandidate      noncanonical derived object
OperationProposal               sole canonical write proposal

ImplementationRollback          restore executable feature baseline
ProjectionRebuildRollback       invalidate/rebuild derived projections
CanonicalStateRollback          governed semantic rollback/replay

Formation-time Semantic Derivation
Query-time Grounded Evidence Interpretation
~~~

`Candidate 默认 OFF`、无命名空间的 `C1/C2` 和研究 `Claim` 不再是规范术语。

---

# 4. 研究假设与效应合同

## ML-H1 — Formation Utility

问题：保留 Raw fallback 的 Formation 是否改善 Simple Recollection 下的有效绑定？

主指标固定为 `ValidBindingRecall`，分析单位固定为 `query × requirement × evidence-role/equivalence-group obligation`。

最小效应固定为：

~~~text
delta_F_min = 0.05 absolute ValidBindingRecall
AND at least 2 net additional valid obligations
~~~

MF-06 run-lock 必须在 effect label 揭示前固定：

~~~text
paired bootstrap procedure
confidence interval rule
correct-case set
~~~

未冻结这些参数，MF-06 不得运行。ML-H1 只在以下全部成立时通过：

1. 直接 Formation fidelity gate 通过。
2. `ΔF` 达到预注册 `delta_F_min`，且 paired 95% CI lower bound > 0。
3. AcceptedBindingPrecision、CurrentStateAccuracy 和适用安全指标不回归。
4. Wrong COMPLETE、scope/authority violation、correct-case regression = 0。
5. 增益不是由更多 hydration、evidence tokens、model calls 或 official actions 造成。

`RequiredEvidenceCoverage`、`ReconstructedCurrentStateAccuracy`、`OperatorReadyRate` 是预指定 secondary outcomes，不能在结果出现后替代主指标。

## ML-H2 — Adaptive Residual Utility

问题：Formation + Simple 后仍存在的预注册 residual，是否需要 observation-conditioned extra action？

ML-H2 只在以下全部成立时通过：

1. Formed + Simple 仍有预注册 unresolved requirements。
2. 在该 residual subset 上，`delta_A_min = 0.05` absolute ValidBindingRecall 且至少净增加 1 个 valid obligation；paired 95% CI lower bound > 0。
3. `IncrementalCostPerAdditionalValidBinding` 不高于 run-lock 预注册上限。
4. Wrong COMPLETE、correct-case regression、authority violation = 0。
5. 增益不来自超出 matched processing ceilings。

`PASS_RETRIEVAL_DOMINANT_RAW_PRESERVED` 使用独立预注册门：`delta_A_raw_min = 0.05` absolute ValidBindingRecall、至少净增加 1 个 valid obligation，且 paired 95% CI lower bound > 0。它不能用 `ΔA|Formed` 的结果替代。

数据量不支持预注册置信程序时，结果只能是 descriptive diagnosis，不能通过 ML-H1/ML-H2。

---

# 5. 执行 Block 与条件 DAG

## MLB-1 — Read-path Decision Boundary

对应 DG-27 与 `DG27-H1`：

~~~text
ProvisionalBinding preserves ambiguity
one final boundary emits AcceptedBinding
Sufficiency / COMPLETE computed on fresh state
known DG-25 Wrong COMPLETE closed
existing correct completion non-regressed
~~~

DG27-H1 未通过，DG-28 effect 不得进入。

## MLB-2 — Minimal Recollection Repair

DG-28 只比较：

~~~text
current product route
vs
each existing eligible official channel called once
+ identity-level union
+ one common downstream DecisionBoundary
~~~

只针对 DG-24 的 6 个 `CHANNEL_ELIGIBLE_NOT_INVOKED` 和 1 个 `CHANNEL_CUTOFF_DROP`。不含模型 planner、second round 或 eval-owned retrieval。

DG-29 只在以下全部有机器证据时进入：

~~~text
one-pass 后仍有 unresolved requirement
fresh observation 提供新 cue
存在未执行的合法 action
second-round official oracle 存在 mediator opportunity
~~~

否则为 `NOT_ENTERED_PENDING_REFINDING_OPPORTUNITY`。

## MLB-3 — Formation First-Loss 与条件 Treatment

MF-01 是观察性 Goal。其 effect 不依赖 DG-28：

~~~text
MF-01 S0–S1 schema / label / trace design
  ↓ label adequacy + Evidence snapshot seal
passive MF-01 S2–S4 effect
~~~

MF-01 terminal 后按 first-loss 条件分支：

~~~text
MF-01
  ├─ MF-02  only if episode first-loss exists
  ├─ MF-03  if identity/event/time first-loss exists
  └─ MF-04  if state/change first-loss exists
~~~

MF-03 可读取 Raw Evidence spans 或已验证 SemanticEpisode artifacts；MF-04 可读取 raw spans、verified identity/time artifacts 或两者。编号不构成依赖。无对应 first loss 时标记 `NOT_NEEDED_BY_FIRST_LOSS`。

## MLB-4 — Evolution Bridge

最小 `EV-01` 不新建 Store，重放：

~~~text
FormationArtifactCandidate
→ OperationProposal mapping
→ deterministic validation
→ StewardDecision replay
→ ClaimVersion / OpenIssue expected disposition
→ as-of current / historical read
→ correction / revocation / CanonicalStateRollback replay
~~~

全生命周期 PASS 要求：

~~~text
UnsupportedCanonicalPromotion = 0
WrongTransitionDisposition = 0
MissingProvenanceClosure = 0
ValidTimeMisassignment = 0
RevocationSupportLeak = 0
RollbackReplayMismatch = 0
~~~

若 label set 没有可验证的 state/change 与 evolution disposition，不可静默标记 EV-01 PASS；项目最多为明确限定范围的 PARTIAL。

## MLB-5 — Conditional Consolidation

MF-05 的 opportunity 与 effect 分开。

Entry / Opportunity Gate：

~~~text
failure requires cross-episode aggregation
raw/member evidence exists
simple formed units cannot form target view
oracle consolidation view can discharge requirement
~~~

无 opportunity 才是 `NOT_ENTERED_NO_CONSOLIDATION_OPPORTUNITY`；有 opportunity 但 treatment 无 mediator gain 是 `PARKED_NO_CONSOLIDATION_GAIN`。

Phase 1 view 仅含 `USER_PROFILE`、`ACTIVE_GOAL`、`DURATIVE_STATE`、`EPISODE_SCENE`。`PROCEDURAL_PATTERN` 留给后续扩展。

## MLB-6 — Factorial Evaluation 与 Integration

MF-06 归因 representation/recollection；DG-30 只集成获证据支持的最小 Read Path 组件，不宣称完整 Memory Architecture ready。

---

# 6. Simple / Adaptive 与 MF-06

`Simple Recollection`：

~~~text
one query-time acquisition phase
deterministic official lanes only
no model planner
no observation-conditioned second action
bounded EvidenceSet selection
typed Binding / Sufficiency
~~~

DG-28 deterministic multi-channel union 仍属于 Simple。

`Adaptive Recollection`：

~~~text
same DecisionBoundary
same total action/hydration/token ceilings
fresh RequirementState after observation
at most one additional admissible action
optional constrained model preference
full Gate / Binding / State / Sufficiency recomputation
~~~

DG-29 这种 observation-conditioned second action 才属于 Adaptive。

| Arm | Representation | Recollection | 用途 |
| --- | --- | --- | --- |
| A | Raw | Simple | 原始基线 |
| B | Raw | Adaptive | Raw 上 adaptive 增益 |
| C | Formed + Raw fallback | Simple | Formation 主效应 |
| D | Formed + Raw fallback | Adaptive | Formation 后 residual 与交互 |
| E | Formed only | Simple | 信息损失负控，永不作为产品候选 |

预注册计算：

~~~text
ΔF           = M(C) - M(A)
ΔA|Raw       = M(B) - M(A)
ΔA|Formed    = M(D) - M(C)
ΔInteraction = [M(D) - M(C)] - [M(B) - M(A)]
~~~

所有 arm 固定：

~~~text
same Raw Evidence and query cases
same access/revocation snapshot
same DecisionBoundary and Binding/Sufficiency
same Operator/Reader identity
same max official actions
same max hydrated Evidence units
same max Reader evidence tokens
same max model calls and rounds
same timeout policy
~~~

Latency 是结果变量，不强制各方法等 latency。

---

# 7. 指标与成本

## Formation fidelity

~~~text
EpisodeBoundaryPrecision / Recall / F1
EpisodeSelfContainedness
CrossBoundaryDependencyRate
RawSpanPreservation
DerivedSupportClosureCoverage
SpanGroundingExactness

EntityMentionRecall
IdentityPairwisePrecision / Recall / F1
FalseCrossScopeMerge = 0
AliasResolutionAccuracy

EventMentionRecall
EventIdentityPairwiseF1
EventDedupPrecision / Recall
DistinctEventPreservation

OccurrenceIntervalAccuracy
TimezoneResolutionAccuracy
AmbiguousTimePreservation
SourceEventTimeSeparationAccuracy

StateAssertionPrecision / Recall
StateTransitionExtractionRecall
TransitionRelationAccuracy
TemporaryConstraintClassificationAccuracy
CorrectionRevocationRecall
ConflictPreservation
~~~

## Evolution

~~~text
CanonicalCurrentStateAccuracy
ValidTimeAccuracy
VersionTransitionAccuracy
UnsupportedCanonicalPromotion
MissingProvenanceClosure
RevocationSupportLeak
RollbackReplayEquivalence
~~~

`ReconstructedCurrentStateAccuracy` 与 `CanonicalCurrentStateAccuracy` 分开；未经 Steward promotion 的 sidecar 只能改善前者。

## Recollection / answer

~~~text
ValidBindingRecall                         ML-H1 primary
RequiredEvidenceCoverage                  secondary
AcceptedBindingPrecision
OperatorReadyRate
TemporalCompletenessRate
FinalAnswerCorrect / F1                   attribution-safe secondary
Wrong COMPLETE
CorrectCaseRegression
~~~

## Revocation / freshness

~~~text
UnauthorizedRawEvidenceLoss = 0
DerivedArtifactRevocationLeak = 0
RevokedEvidenceRetrievalLeak = 0
StaleProjectionRead = 0
CanonicalSupportReevaluationCoverage
RevocationPropagationLagP95
FormationCoverageWatermark
FormationPendingEvidenceCount
RawFallbackActivated
~~~

## 成本与效率

写时与读时分开：

~~~text
FormationCostPerEvidence
FormationStorageAmplification
ProjectionBuildLagP95
RebuildCost

OfficialRetrievalCalls
HydratedEvidenceUnits
BindingComputations
ModelCalls
QueryLatencyP50 / P95
QueryCostPerUsefulBinding
IncrementalCostPerAdditionalValidBinding
~~~

MF-06 run-lock 必须在 effect label 揭示前固定 primary amortization horizon `H_primary`，并额外报告 `H = 1, 10, 100` 次读取的敏感性分析。未标明 H 时不得报告 `RepresentationCostPerUsefulBinding`。

---

# 8. 开发尝试、研究结论与修复循环

一次运行失败不等于 Goal 终止：

~~~text
ATTEMPT_FAILED
  某次实现、协议、服务或实验尝试未产生有效 treatment

HYPOTHESIS_NOT_SUPPORTED
  有效、完整、可评分的 treatment 没有达到预注册效应

GOAL_TERMINAL
  已得到足以停止该局部路线的证据，或发生实际安全/数据边界破坏
~~~

失败分类与处置：

| 分类 | 当次处置 | 后续 |
| --- | --- | --- |
| `TRANSIENT_INFRASTRUCTURE` | 允许 1 次完全相同的 transport retry | 仍失败则进入根因修复，不改 treatment |
| `PROTOCOL_OR_IMPLEMENTATION` | fail-closed，离线复现，修通用合同 | targeted test → one canary → 新的 superseding iteration |
| `VALID_TREATMENT_NO_GAIN` | 完成预注册分析 | 可 PARK 对应假设，不自动停掉无共享根因的 Program |
| `AUTHORITY_OR_DATA_BREACH` | 立即停当次 effect，隔离影响 | 只有实际越权、非授权 Evidence 丢失、失控 Canonical mutation 或数据损坏才进入 FAIL |

统一开发循环：

~~~text
offline reproduction
→ classify root cause
→ minimal generalized fix
→ synthetic/contract fixtures
→ touched component regression
→ one real canary
→ protocol-valid: run matched effect in parallel
→ seal unscored output
→ score, reflect, and choose next treatment
~~~

不允许用 case ID、gold、答案、seed 或个别 Prompt 补丁修复失败。同一通用根因最多进行 3 个有机器证据的修复迭代；仍重复时转入架构备选方案评审，而不是默认结束整个 Program。

---

# 9. 执行进度与当前授权

1. DG-27 协议错误已经过通用修复形成有效 effect；其后的 Wrong COMPLETE/回归证明“模型解释器充当共同决策边界”不可采用，但不再阻断独立的 Formation 和确定性 Read Path 工作。
2. MF-01、DG-28 Lite、MF-03、MF-04、EV-01 和 DG-30 已依次封存；DG-29 因 Formed+Simple 已无 residual requirement 而不进入。
3. MF-06 已完成不新增 retrieval call 的 A/C 描述性归因。它可支持“Formation 补上了开发集最后 1 个 Binding”的工程判断，不支持 ML-H1 泛化主张。
4. MD-01 已在用户明确授权下完成统一 `MemoryFormationBundleV01`、`SemanticEpisodeCandidateV01`、10-conversation label seal 与直接 Formation effect；MD01-H1/H2 仅在该封存 non-holdout validation 上支持。
5. MF-02 已在 scorer 实现前分别封存 8-case repair-dev 和 24-case sealed validation，完成唯一次四臂 direct + anchor-fixed simple-read effect。H1/H2 均通过，但 formal holdout、产品 flag 和 product-shadow 仍未授权。
6. MD-02 已在新封存的 24-case validation 上完成各一次 boundary 与 official-path observation-only shadow effect。H2 全门通过；H1 因唯一 over-split 令增量 `0.027778` 超过 `0.02` 而 MISS。当前只保留 shadow contract，V02 不采用，且不使用 sealed case 回调规则。

当前已执行证据收敛为两个轻量 lane；没有由 MD-02 自动派生的新执行授权：

~~~text
Lane A — Formation generalization set
  MD-01 contrasting episode set and unified bundle: PASS
  MF-02 four-arm direct + anchor-fixed simple read: PASS
  MD-02 observation-only shadow: H2 PASS; V02 boundary: H1 MISS
  → keep the default-OFF typed shadow contract; reject current V02 policy
  → any new boundary policy requires fresh repair/sealed data and new authorization
  → do not tune on either MF-02 or MD-02 sealed sets

Lane B — Read-path release evidence
  keep deterministic DG-28 + formed sidecar
  → expand matched non-holdout validation
  → rerun Reader only after evidence/operator correctness is sealed
~~~

不授权：自由 action planner、DG-29 多轮 refinding、formed-only 产品路径、新 durable schema、默认开启 feature flag 或 formal holdout。GPU 只在新标签中出现确定性 Formation 无法解析的语义缺口时使用；默认 CPU 重放和批处理，不为了“利用 GPU”而增加模型路径。

---

# 10. Terminal 分类与可达性

fail-closed 拒绝的协议错误是 `REPAIR_ITERATION`，不是安全 FAIL：

~~~text
if attempt_protocol_failure and fail_closed and no_state_escape:
    REPAIR_ITERATION
elif actual_authority_breach_or_data_corruption:
    FAIL_<reason>
elif lifecycle_label_adequacy_failed:
    PARKED_INSUFFICIENT_LIFECYCLE_LABELS
elif valid_complete_treatment_has_no_preregistered_gain:
    PARK_OR_ROUTE_BY_FIRST_LOSS
elif read_path_complete and formation_or_evolution_not_evaluable:
    PARTIAL_READ_PATH_ONLY
elif MF06_complete and applicable_EV01_complete:
    classify_by_preregistered_factorial_effects()
else:
    ACTIVE_DEVELOPMENT
~~~

| 类别 | 必要条件 |
| --- | --- |
| PASS | 有效 treatment 完成且预注册效果/安全门通过 |
| PARTIAL | 某 Program 完成，其他范围因标签或数据不可验证，未验证范围明示 |
| PARKED | 已有有效证据证明无 opportunity、无 mediator gain 或根因在其他 Plane |
| FAIL | 实际 authority/scope/Evidence preservation/canonical safety 破坏，或有效 treatment 产生 Wrong COMPLETE / correct-case regression |

Factorial terminal 分类保持 1.1 的预注册定义：

| Factorial 条件 | Terminal |
| --- | --- |
| ML-H1 PASS；ML-H2 不通过或无 residual opportunity | `PASS_FORMATION_DOMINANT_SIMPLE_READ` |
| ML-H1 PASS；ML-H2 PASS | `PASS_FORMATION_AND_RECOLLECTION_COMPLEMENTARY` |
| ML-H1 不通过；`ΔA|Raw` 达到预注册增益且安全 | `PASS_RETRIEVAL_DOMINANT_RAW_PRESERVED` |
| Formation 无下游增益；Raw/formed 上 Adaptive 也无增益 | `PARKED_FORMATION_AND_RECOLLECTION_NO_GAIN` |
| `M(E)-M(C) ≤ -0.05` 且 paired 95% CI upper bound < 0 | 强制保留 Raw fallback，记录 information-loss finding |

禁止使用 `PASS_COMPLETE_MEMORY_ARCHITECTURE`、`PRODUCTION_READY` 或 `FORMAL_HOLDOUT_PASS`。

---

# 11. 轻量开发与分层质量门

修复迭代按风险分层，不每次重跑全部系统：

1. 每次编辑：touched unit/contract fixtures + edited-file Ruff/mypy。
2. canary 前：相关 component suite 和直接 regression。
3. matched effect 前/终态前：一次预注册范围回归。
4. 只有修改 PostgreSQL、security、public MCP 或 frozen architecture 边界时，才跑对应全量门。

制品上限：每个有效 effect 只保留 `run-lock.json`、`results.json`、`terminal.json`和一份 compact `repair-log.jsonl`（需要时）。协议修复过程不生成逐阶段 receipt、transitive manifest、deliverable index、重复 runbook 或 reviewer loop。

自动 retry 仅用于一次同请求 transport 故障；不对 schema/semantic invalidity 盲目重试。不做 case-ID/answer/gold-aware rules、Prompt/Top-k/seed sweep、eval-owned retrieval、formed-only product path、自动 Canonical promotion 或无界 refinding。

---

# 12. 当前唯一执行导航

1. 保留 DG-27 V03 负结果，不把它扩大成自由模型决策路径。
2. 产品候选保留 `DG-28 deterministic union + MF-03 sidecar`；普通回忆改为 governance admission + soft ranking，完整 Binding/Sufficiency 只用于 strict typed operator。feature flag 仍 OFF。
3. MD-01 已增加真正含 continuation/topic-shift/session/time-gap/correction 对照的 Formation validation；MF-02 随后在独立封存的 24-case non-holdout set 上完成四臂比较，`MF02-H1/H2` 均支持。
4. MD-02 已证明 default-OFF observation-only shadow 在 official read path 旁路的行为等价与 freshness-safe（H2 PASS），但当前 V02 的 over-split 非劣门 MISS；保留 shadow contract、拒绝 V02，不进入 topology/admission 或产品启用。
5. `MILA-ML-CLOSURE` 已 terminal；ML-R01 R4 已按用户限制形成 explicit checkpoint seal，不重开旧 C0～C4、DG-29 或已成功 ML-R01 cells。
6. ML-R02 已以 `COMPLETE_USER_LIMIT_8X4` 封存，全部成功 cells 与 terminal 不再 resume、覆盖或重跑。
7. GDPM-01 的 24-case context-only canary 已由 `gdpm-b0-20260901-003` 封存为 repair-required，并结束活动写权；其 4/24、14 个 ContextReceipt 缺失和 6 个 MCP output-limit 是 MVP U0 的前驱诊断。
8. 当前唯一活动 Goal 为 MVP-01；用户已授权 U0→U3 顺序连续执行，无需逐阶段重新请示。U0 24-case context-only 已由 `017` 以 24/24 PASS 封存；warm-001 与 warm-002 均已不可变 FAIL。Master 当前只打开 fresh `mvp01-u0-warm-repair-probe-20260901-002` 10-class synthetic production-path repair probe；其 PASS 和 independent auditor GO 前，新的 100-request formal successor、benchmark、Reader/Answer/Judge、128/500 与 formal holdout 均未打开。

局部合同：

- [Program C Read Path / Recollection Master](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
- [Program A Memory Formation Master](./MiLAi_MF-01-MF-06_Memory_Formation_and_Representation_MASTER.md)
- [ML-R01 predecessor 修复与验证 Goal](./MiLAi_ML-R01_ProjectionWorker租约与Formation送达Binding闭环修复_GOALS.md)
- [ML-R02 已封存 predecessor](./MiLAi_ML-R02_统一MemoryLifecycle架构收敛与LongMemEval验证_GOALS.md)
- [GDPM-01 前驱 Goal](./MiLAi_GDPM-01_受治理双过程Memory分阶段开发与验证_GOALS.md)
- [当前 MVP-01 高效可用 Memory 最小闭环 Goal](./MiLAi_MVP-01_高效可用Memory最小闭环_GOALS.md)

本文件是唯一执行顺序来源；项目级 Master 只负责稳定架构边界，局部 Goal 只负责本 Goal 的实现与 effect contract。

---

# 13. 当前活动入口：MILA-MVP-01 / U0

`MILA-ML-CLOSURE@0.2` 已执行并终结为：

```text
PARKED_ML_CLOSURE_LONGMEMEVAL_BELOW_TARGET
release decision: KEEP_FLAG_OFF
formal holdout: NOT_RUN
```

它的 500-case 成绩是有效的端到端产品失败观测，但由于 Candidate 477/500 context failure、5 个 worker exit 和 `formation_applied=0`，不能用于判定 Formation 方法效果。

ML-R01 的 R4 以 explicit checkpoint seal 结束当前活动写权：

```text
checkpoint:           var/ml_repair/ml-r01-20260831-001/checkpoints/r4/context-seal-8.json
scope:                USER_LIMITED_8_CASE_PILOT
contexts:             32/32 succeeded
R/F snapshot:         8/8 exact
cleanup/resource:     FAIL_CLOSED_SEPARATE_OPERATIONAL_WINDOW
answers/judges:       0/0
formal holdout:       NOT_RUN
```

ML-R02 已完成用户限定的 8×4 并结束其活动写权：

```text
terminal:             var/ml_r02/ml-r02-20260831-004/terminal.json
status:               COMPLETE_USER_LIMIT_8X4
terminal cells:       Context/Answer/Judge/Score = 32/32 each
128/500:              NOT_STARTED
formal holdout:       NOT_RUN
```

GDPM-01 当前 24-case attempt 已封存并移交：

```text
terminal:             var/gdpm/gdpm-b0-20260901-003/terminal.json
status:               FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED
contexts:             4/24 PASS; 20/24 PROTOCOL_IMPLEMENTATION
root causes:          14 missing ContextReceipt; 6 MCP wire output-limit
Reader/Answer/Judge:  0/0/0
formal holdout:       NOT_RUN
```

MVP-01 的首个 100-request warm attempt 已不可变失败封存：

```text
terminal:             var/mvp01/mvp01-u0-warm-20260901-001/terminal.json
terminal SHA-256:     babf44c832e77c36940293dc4e80f8360adf862db331eb531c36925952893fef
status:               FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED
request/logical:      100 typed terminal / 0 logical Context attempt
Runtime attempts:     1
Context terminal:     0/100
Reader/Answer/Judge:  0/0/0
formal holdout:       NOT_RUN
results SHA-256:      90f8bbb4091af371a9940fd4fbb5bd814ffff44a7e8b092259e7293b9820740e
checkpoint SHA-256:   b4dcb90829c83a25fd26fcdae301ef2571ddc1908e9bd761dada2b71173bf089
run-lock SHA-256:     5a60715910008bd7445d3f7d43c61c61c92fffde0aefb074627f3d584819cc72
```

失败反思：`session_ordinal` 属于 immutable evaluation Event identity，不是 Runtime
`EvidenceSourceContext` 的公开字段；adapter 将其混入 strict `extra="forbid"` wire，导致首个并发波
4/4 capture 返回 HTTP 400。旧 cleanup helper 又把 0-ingest 错当成必须清理 20 条，遮蔽了主失败。
修复没有扩展公开 MCP 或 Runtime schema，而是把 ordinal 留在独立 `source_event_identity`，并增加真实
Runtime model 的 20-payload preflight、完整 mixed-wave outcome accounting、0-denominator cleanup、
diagnostic fail-closed terminal sealing、固定日志/ownership 摘要复验和 database/drop identity 三方绑定。
独立审计进一步指出进程释放证据仅有 ownership 哈希、未与 Runtime 返回 PID 逐字段绑定。
现已原样封存 API/worker process mappings，交叉验证 PID、launcher、interpreter、cwd 和 cmdline
digest，并在 artifact seal 重读后以 PID + `/proc` start ticks 证明 exact process 已终止；
PID reuse 可证明原进程缺席，任何 `/proc` 权限、读取或解析异常均 fail closed。

修复后的 bounded production-path witness 已封存：

```text
terminal:             var/mvp01/mvp01-u0-warm-repair-probe-20260901-001/terminal.json
terminal SHA-256:     a4b8331d0666824407693a44de9349e69750c5628691169e6e0022505266f775
results SHA-256:      c52bf2496e5492132a49d128f4a3597f83bbff87bae67fb9db7f0fccc3f02c0c
path:                 fresh Runtime API + persistent worker + real stdio MCP
capture/context:      2/2 synthetic captures across session ordinals 0/1; 1 Context resolve
cleanup:              actual=2 terminal PASS; independent actual=0 terminal PASS
Reader/Answer/Judge:  0/0/0
benchmark/holdout:    0 / NOT_RUN
resource release:     API/worker exact process absent; port closed; ownership RELEASED; DB drop PASS
```

该 probe 只证明 `session_ordinal` production-path 根因关闭，不替代 warm-002 的 100-request acceptance。

warm-002 已自然终结并不可变封存：

```text
terminal:             var/mvp01/mvp01-u0-warm-20260901-002/terminal.json
terminal SHA-256:     51e4961de03514d9fe3d79c9c653f6ef49d93849c6bce30a0f1ae63ab4741db0
results SHA-256:      fb8958447c681d1cd80cd8f35085a831d4488804cca99e6b7b47196b077afc1d
checkpoint SHA-256:   31b37c8980932f822673c1b4672efccbc01bffe137a93b89b42cba23f0e38c18
run-lock SHA-256:     de720a2f713e944fdb64a5c73a155ff63bd1353ad7d53fa3369415fdb75cd301
status:               FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED
request/logical:      100 / 100
Runtime attempts:     1
sealed archives:      90
Reader/Answer/Judge:  0/0/0
benchmark/holdout:    0 / NOT_RUN
resource release:     PASS; API/worker exact process absent; port closed; ownership RELEASED; DB absent
```

独立审计判定 successor `NO-GO`。002 的文件、denominator、process、port、database、ownership、cleanup
和 SHA 链真实完整，但其 `0/100 Context terminal` 不能解释为产品成功率：50 个 Runtime `HIT` 因
`DG15Provenance` tuple 被 live archive validator 当作非 list 而确定性假 FAIL；90 个 archive 的
`SessionIdentityIntegrity` 又因 B0 metric 漏哈希 `source_event_identity` 而假 0；TX-05 cleanup 的真实
12 个 delivery / watermark 60 被陈旧的 8 / 40 exact gate 必然拒绝。failure wrapper 还把已有 Runtime
status、receipt、retry、span 和 context evidence 抹成通用 `SYSTEM_FAILURE`。这些 evaluator 缺陷不得用于
回填、重封或改写 002。

去除 evaluator 假失败后，30 个 context-bearing `ABSTAINED` 是真实 typed semantic-abstention outcome，
在 expectation 与 evidence/receipt 完整性成立时不是 U0 delivery failure；其中 Bicycle 仍需修复同一 Evidence
被 D1/E1 重复映射的 receipt losslessness。10 个中文 allergy `ABSENT` 是合法 typed safe-empty terminal，
但不满足本 run-lock 的正向 evidence-anchor fixture expectation，receipt 对该空结果为 N/A。另有 10 个
Atlas window-count protocol invariant failure。Atlas 的 bounded raw response preimage 未在 adapter 抛错前封存，因此必须先增加
诊断 preimage，再修 producer 分母，不能直接放宽 invariant。修复必须同时满足：archive live/JSON
round-trip 等价、B0 三段 governance digest、12/60 projection exactness、诚实 typed failure row、Dense
召回、Atlas window denominator 与 Bicycle alias losslessness。

当前唯一活动 Goal：

```text
active goal:          MILA-MVP-01@0.1
active stage:         U0
case scope:           MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE
run scope:            MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE
run lock:             var/mvp01/mvp01-u0-warm-repair-probe-20260901-002/run-lock.json
Reader/Answer/Judge:  FORBIDDEN_IN_CURRENT_SCOPE
benchmark cases:      FORBIDDEN; SYNTHETIC_FIXED_FIXTURE_ONLY
evidence hard cap:    8192 Qwen tokens
required PASS gate:   24/24 context-only canary PASS (`017`)
immediate predecessor:warm-002 immutable FAIL; never replayed/resealed/reclassified
repair witness:       fresh 10 query classes × 1 production-path probe required
formal successor:     NOT_AUTHORIZED_BEFORE_PROBE_PASS_AND_AUDITOR_GO
next ladder:          repair probe → independent audit → fresh 100 warm → U1 targeted fixtures
U1/U2/U3:             AUTO-ADVANCE_ONLY_AFTER_PREDECESSOR_GATE
formal holdout:       FORBIDDEN_WITHOUT_SEPARATE_AUTHORIZATION
public MCP/schema:    NO CHANGE AUTHORIZED
product default flag: OFF
next gate:            PASS_MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE
```

禁止：resume/replay/overwrite/reseal 002；把 50 个可重放 archive 回填为 002 PASS；仅放宽
window/receipt/status validator；增加 retry、model、benchmark、Reader/Answer/Judge 或 holdout；在 fresh
10-class production-path probe 与 independent auditor GO 前授权新的 formal warm run。

# 14. 2.0 优化基线

后续开发统一使用以下简化：

```text
Write:
  Raw Evidence
  → reversible Episode / Identity / Time projection
  → optional governed StateProposal

Ordinary Read:
  governance admission
  → simple BM25/Dense/formed union
  → soft ranking + coherent context
  → Reader

Strict Read / Commit:
  COUNT / range / current-version / conflict / mutation
  → RequirementState / Binding / typed proof
  → Operator or governed Canonical procedure
```

Harness 规则：

1. product delivery、semantic method、Reader 和 release 分栏报告，不再压成一个开发期 Overall gate；
2. 每个 case 使用唯一 namespace，benchmark shard 结束后删除隔离数据库，不把逐 case 物理清理计入 read algorithm 关键路径；
3. Raw/Formed 两臂共享同一 ingest/projection snapshot，只在 query-time 分叉；
4. GDPM 主 matched evidence budget 为 4096；1024 只作 MiLA-Fast/MiLA-Dual efficiency pressure，不建立 512/2048 人工二分；
5. 24/128/500 分块单独授权；当前不创建任何 benchmark case cell；
6. Wrong COMPLETE 阻止发布，但普通 protocol/implementation miss 进入 repair loop，不终止无共享根因的 Program。

本入口不改写任何历史 terminal，也不授权 `DEFAULT_ON`、production-ready 声明或 formal holdout。
