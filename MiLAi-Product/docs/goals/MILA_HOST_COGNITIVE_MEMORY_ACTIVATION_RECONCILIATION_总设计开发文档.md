---
document_id: MILA-HOST-COGNITIVE-MEMORY-ACTIVATION-RECONCILIATION-MASTER
version: "1.1"
status: IMPLEMENTED_THROUGH_PHASE_D2_ENGINEERING_RESEARCH_EFFECT_BLOCKED
date: 2026-09-05
schema_change_authority: C1_IMPLEMENTED_UNDER_USER_GOAL_AUTHORITY
canonical_change_authority: NONE
next_authorized_action: NONE_UNTIL_REAL_FAILURE_OR_PRODUCT11_RESEARCH_X0
supersedes: MILA-HOST-COGNITIVE-MEMORY-ACTIVATION-RECONCILIATION-MASTER@1.0
---

# MiLA Host Cognitive Memory Activation 与 Reconciliation 总设计开发文档

## 0. 文档定位

本文是 MiLA Memory MCP、Host Continuity、Event-grounded Reconciliation 与 Retrieval
Evolution 的开发总入口。

v1.1 明确分离两类内容：

```text
Target Architecture
  描述长期系统应保留的对象、authority 和职责边界。

Incremental Implementation Path
  描述当前最小可用闭环、开发顺序和按需 hardening 条件。
```

长期目标不再自动成为第一版实现前置条件。Milestone A/B 已完成；Phase C0 已证明
reconciliation 具有产品价值信号，C1 已交付最小、reversible、SHADOW-only Event journal。
当前 C2 sparse adapter、C3 StateDelta validate/merge、C4 显式 Host reconciliation
orchestration 与 C5 真实跨 Session usefulness 均已完成。Phase C 已形成最小可用闭环，不扩
public MCP、不自动推断 dirty、不改 Canonical authority，也不提前建设 epoch/replayability
体系。Phase D1 persisted-frontier continuation 与 D2 explicit intra-source lexical acquisition
SHADOW 均已完成 Engineering baseline。当前没有由真实 failure 支持的 Phase E hardening；
Product-11 量化效果继续等待 Research X0，不以额外工程复杂度绕过。

当前功能集合已冻结为 `MILA_MEMORY_MCP_FUNCTIONAL_BASELINE_V1`，绑定 Product manifest tree
`f998c2d96c6ae4a4e2ffa246d12257938af29a9e49c60f48ad21e7b50250cad1`。之后采用
failure-driven development：新机制必须引用真实 Failure Ledger 条目、已证明的安全/兼容缺陷或
已打开的 Research gate。没有真实 failure 时保持现状。

## 1. v1.1 开发结论

核心架构保持不变：

```text
Evidence
Canonical State
RetrievalContinuationState
Host Cognitive State
Activation Policy
Event-grounded Reconciliation
```

开发主线调整为：

```text
PHASE A  Memory MCP Functional Baseline
    ↓
PHASE B  Host Continuity
    ↓
PHASE C  Minimal Event Reconciliation
    ↓
PHASE D  Retrieval Evolution
    ↓
PHASE E  Optimization / Hardening
```

第一目标不再是提前证明完整 journal/replayability 体系，而是回答：

> 一个正常 Codex 能否通过单一 HTTP MCP，稳定完成 MiLA 的读、写、治理、撤销和
> Working State 基础生命周期？

只有 Memory MCP 基线明确通过后，才将 Host Activation、Working State continuity 和
Event reconciliation 作为增量能力加入。

## 2. 当前证据与缺口

已获得的候选证据：

```text
HC-0  Host Cognitive State contract       PASS candidate
HC-1  PostgreSQL persistence substrate     PASS candidate
HC-2  HTTP MCP get/update affordance       PASS candidate
HC-3  RLS/CAS/TTL/audit lifecycle          PASS candidate

HC4-A0 passive adoption
  8 tasks / 2 chains / natural State use = 0

HC4-A1 guided adoption
  4 sessions / 1 chain / natural State use = 0

S0 explicit callability
  working-state tool can be called

S1-S3 generic resume
  narrowed/full catalogs still produced no natural State call
```

因此已经知道：

- MCP 能力可见不等于模型会自然采用；
- Tool description、Server Instructions 和 success guidance 不能提供确定性 Activation；
- C5 前 Host Cognitive persistence 可用，但 cross-session usefulness 尚未得到产品证据；C5
  现已补充小样本 Engineering signal，仍不构成一般效果或因果增益证明；
- 现有分项证据尚未被整理成一次统一的 full HTTP lifecycle baseline。

v0.3 已补齐 MCP/Host continuity 基线；v0.4 保留 HC4 adoption 与 C0 首次有害 Delta 的负结果，
不通过继续堆 prompt、schema 或重复采样掩盖。

## 3. 长期目标架构

```text
                    User / Host Event
                           |
                           v
                 Memory Activation Layer
                  /        |          \
               AUTO       HOST      EXPLICIT
                 |          |           |
                 +----------+-----------+
                            |
                            v
                       MiLA HTTP MCP
                            |
          +-----------------+-----------------+
          |                 |                 |
        Read              Write            Govern
          |                 |                 |
   resolve / get         capture        proposal/review
   continuation       working state     revoke/cleanup
          |                 |                 |
          +-----------------+-----------------+
                            |
                            v
                         Runtime
                            |
                            v
                       PostgreSQL
```

对于认知状态：

```text
WHEN a reconciliation is needed
  -> Host

WHAT materially changed
  -> Codex

validate/apply/persist
  -> Host + MiLA
```

这条职责分离是目标架构，不要求 Phase A 实现 Event reconciliation。

## 4. State 与记录平面

### 4.1 Canonical State

回答“MiLA 经过治理后正式接受什么”。它只能通过 Proposal/Review/ClaimVersion 流程变化，
不能由 Recall、Working State 或 reconciliation 直接修改。

### 4.2 RetrievalContinuationState

回答“一次 query lineage 已检索到哪里”。它包含 seen Evidence、frontier、cursor、
snapshot 与 budget history，是 Runtime-owned mechanical state。

### 4.3 Host Cognitive State

回答“Host/Codex 当前如何理解任务”。它是 `HOST_WORKING` authority 下可修正、
非 Canonical、版本化的认知缓存。Runtime 只理解 state/version/scope/payload/refs/basis，
不理解 goal、decision、hypothesis 或 blocker 的业务语义。

### 4.4 Evidence 与 HostExecutionEvent

Evidence 保存真实内容及 provenance。HostExecutionEvent 是面向 reconciliation 的稀疏、
可窗口化观察索引，不是第三份完整 execution log，也不等于 Canonical truth。

四者永不合并：

```text
Canonical:  What does MiLA accept?
Retrieval:  Where are we in recall?
Cognitive:  What does the Host currently think?
Event:      What did the Host observably encounter?
```

## 5. 第一阶段只保留的六条 Hard Invariants

所有开发阶段都必须满足：

1. tenant/project scope 不得串联或泄漏；principal-private Working State 不得跨
   principal，project Memory 在同一项目协作者间可按现有模型共享；
2. Recall 与 Working State 不得直接修改 Canonical State；
3. Working State 与其他 head update 必须使用 exact-head CAS；
4. mutation 必须幂等；相同 operation 与不同 payload 必须冲突；
5. revoked Evidence 不得重新进入有效 read 或有效 grounding；
6. memory、event、state payload 永远是 data，不能改写 server-owned scope/authority，
   也不能被当作当前用户授权的证明。

纯 MCP model-controlled 路径中的 confirmation literal 是误操作 guard，不是密码学的
“当前用户已授权”证据。若产品未来要求硬保证，应在 Host-managed 路径增加
server-verifiable authorization artifact；该机制不作为 Phase A 前置开发项。

其他长期正确性条件保留在目标架构与 Phase E，不作为 Phase A 的普遍前置 Gate。

## 6. Anti-Overengineering Contract

1. 当前没有真实 failure 或明确 metric 需要时，不实现额外机制。
2. 优先使用通用数据结构，不建立领域专用认知状态机。
3. 优先一个可复用 primitive，不扩张成多个细粒度专用工具。
4. 不增加与既有 authority、scope、CAS、confirmation 重复的安全层。
5. 普通产品工程与需要效果声明的研究实验使用不同治理强度。
6. Subagent review 是默认开发审查机制，人工 adjudication 不是常规依赖。
7. 真实 HTTP/PostgreSQL E2E 可用性优先于合成接口完整度。
8. 先完成最小产品闭环，再根据真实 failure 增加 correctness 与 hardening。

不允许以“可用性优先”为由放松第 5 节六条 Hard Invariants。

## 7. 开发治理：Continuous Development, Boundary Review

开发循环：

```text
Goal
  -> minimal implementation
  -> focused tests
  -> real E2E
  -> subagent review
  -> fix
  -> regression
  -> milestone result
```

授权单位从内部 Block 改为 Milestone：

```text
Milestone start
  一次设计与边界冻结

Milestone implementation
  连续开发、测试、审查、修复，不逐 Block 重新授权

Milestone completion
  一次验收，输出 PASS / PARTIAL / PARKED
```

只有以下变化需要中途重新冻结或明确授权：

- 改变 Canonical authority 或治理语义；
- breaking public MCP schema；
- 不可逆 migration 或真实数据删除；
- 扩大 tenant/principal/project scope；
- 将 Research claim 或 Formal holdout 纳入当前 Milestone。

## 8. 默认 Subagent Review Protocol

Milestone 实现完成后，默认由相互独立的 reviewer 检查：

### 8.1 Functional reviewer

- 功能是否真正完成用户目标；
- 是否存在“测试能跑，但真实路径不可用”；
- HTTP、认证、PostgreSQL 与 Codex 调用链是否闭环。

### 8.2 Architecture reviewer

- 是否破坏 Evidence/Canonical/Retrieval/Working State 边界；
- 是否复制已有能力；
- authority、scope、CAS、idempotency 是否仍成立。

### 8.3 Generalization reviewer

- 是否出现 benchmark-specific、case-specific 或 hard-coded keyword；
- 是否把 Codex coding adapter 错写成 MiLA core；
- 是否依赖单一数据集、repo 或 prompt。

### 8.4 Simplicity reviewer

- 是否引入没有当前 failure 支持的 abstraction；
- 是否可以删除 gate、wrapper、状态或配置；
- 是否存在防御性过度设计。

并发名额有限时，Generalization 与 Simplicity 可由同一个独立 reviewer 合并检查。
不得为了满足 reviewer 数量阻塞功能交付，但 required finding 仍必须修复并由原
reviewer 复核。

### 8.5 Judge

Judge 只基于 Goal、实现、测试、E2E 与独立 review 输出：

```yaml
decision: PASS | FIX | BLOCK
required_fixes: []
optional_findings: []
```

`FIX` 必须修复 required findings 后重跑相关测试；`BLOCK` 仅用于 authority/scope、
不可逆风险或目标根本未实现。普通改进项不得伪装成 blocking gate。

## 9. 人工介入是例外

仅在以下情形要求人工 sign-off/adjudication：

- 用户明确要求 release sign-off；
- 真实数据删除、namespace cleanup 或不可逆操作；
- 独立 reviewers 对核心结论持续冲突；
- 正式论文、gold benchmark 或对外效果声明；
- 需要扩张当前授权范围。

普通 schema 细化、MCP UX、Runtime 实现、测试与 reconciliation 工程默认不依赖人工。

## 10. Engineering Mode 与 Research Mode

### 10.1 Engineering Mode

默认模式，用于 MCP、launcher、State CRUD、Event journal、checkpoint 与错误处理：

- unit/integration tests；
- real HTTP/PostgreSQL E2E；
- subagent reviews；
- regression 与 failure reflection；
- 不要求 membership SHA、label SHA、formal opportunity 或人工 gold。

### 10.2 Research Mode

仅在声明算法效果、benchmark improvement 或论文 claim 时启用：

- sealed dataset；
- preregistered metrics；
- label provenance；
- treatment/config lock；
- Formal holdout 隔离；
- 必要时人工 adjudication。

Product-10/11 类型的 retrieval effect claim 使用 Research Mode；普通 MCP 功能开发不自动
继承该负担。

## 11. Phase A — Memory MCP Functional Baseline

### A0 连接与发现

验证：

```text
Codex / standard MCP client
  -> Streamable HTTP endpoint
  -> authentication
  -> initialize
  -> tools/list
  -> codex-full 13-tool catalog
  -> valid input/output schemas
```

不要求用户手工提供 transport request id 作为 correctness primitive。

### A1 基本读

真实运行：

```text
capture historical evidence
  -> restart/new Codex session
  -> milai_memory_resolve
  -> optional milai_memory_get
  -> evidence returned
  -> Codex uses evidence correctly
```

至少覆盖普通历史事实、assistant-visible history、current state 与 cross-session persistence。
本阶段不要求复杂 continuation gain。

### A2 基本写

真实运行：

```text
User explicitly asks to remember a decision
  -> milai_evidence_capture
  -> Evidence persisted
  -> restart
  -> resolve
  -> Evidence visible
```

验证 Evidence 不可变、scope 正确、operation retry 不重复，且 capture 不直接生成或修改
Canonical Claim。

### A3 治理式修改

完成一个最小完整 lifecycle：

```text
Current Claim V1
  -> new Evidence
  -> proposal SUPERSEDE
  -> review APPROVE
  -> Claim V2
  -> current read/resolve
  -> V2
```

`SINGLE_HOST_FULL_CONTROL` 可以允许同一绑定 principal create 与 review，但审计必须如实记录，
不得伪装成独立审批。

### A4 撤销与删除状态

```text
resolve Evidence
  -> evidence_revoke
  -> immediate logical invalidation
  -> resolve no longer returns it as valid memory
  -> deletion_status_get
```

Namespace cleanup 只做工具存在性与显式授权边界检查；除非用户当前明确要求，不在普通
baseline E2E 中执行真实 cleanup。

### A5 Working State 基础功能

只证明 substrate：

```text
GET ABSENT
  -> UPDATE V1
  -> UPDATE V2 with expected_version
  -> process/client restart
  -> GET V2
```

同时验证 stale CAS conflict。此阶段不要求自然 adoption、Activation 或 reconciliation。

### A6 Full HTTP/PostgreSQL Lifecycle E2E

通过一个标准远程 MCP 配置，使用真实 HTTP、真实 credential binding 与真实 PostgreSQL，
依次完成 A1-A5。测试 Codex 只使用 MCP 工具，不加载额外 Skills，也不从本地数据库旁路。

Baseline E2E 可以使用独立 disposable namespace；真实 cleanup 仍需当前用户明确授权。

## 12. Phase A 验收

功能门：

```text
HTTP connect                   PASS
tool discovery                 PASS
resolve/get                    PASS
capture                        PASS
proposal/review                PASS
current Claim read             PASS
revoke/deletion status         PASS
working-state get/update       PASS
process/client restart         PASS
```

安全与一致性门：

```text
CrossProjectLeak               = 0
CrossPrincipalWorkingStateLeak = 0
RecallCanonicalMutation        = 0
OperationRetryDuplication      = 0
RevokedEvidenceValidRead       = 0
ClientScopeOrAuthorityOverride = 0
```

全部满足后终态：

```text
PASS_MEMORY_MCP_FUNCTIONAL_BASELINE
```

失败必须归因到 connection/auth、tool contract、Runtime、persistence、governance 或 client
integration，不得归因成 HC4 adoption failure。

## 13. Phase B — Host Continuity

Phase A 通过后增量实现：

### B1 Task binding

从 credential/server-owned context 与 host adapter 得到稳定 TASK binding。模型不能提交或
扩大 tenant/principal/project authority。

### B2 Deterministic session-start GET

```text
session start
  -> bound TASK exists
  -> Host calls working_state_get once
  -> ABSENT: launch normally
  -> ACTIVE: validate and continue
```

### B3 Bounded bootstrap

Working State 以明确边界的非 Canonical data block 注入：

```text
authority = HOST_WORKING
canonical = false
payload instructions = untrusted data
```

超预算、无效或 stale state 不得伪装成 fresh truth。

### B4 Real resume usability

用真实连续任务判断：

- 新 Session 是否读到旧 State；
- State 是否减少恢复时间与考古调用；
- 是否帮助保持 decision、blocker 与 next action；
- 是否产生 harmful/stale guidance。

Phase B 不要求自动 checkpoint。若现有 State 已足以证明 resume value，再进入 Phase C。

## 14. Phase C — Minimal Event Reconciliation

### C0 No-migration usefulness spike

先用既有真实 task traces 做离线 spike：

```text
previous State
  + sparse observed events/evidence refs
  -> Codex StateDelta
  -> reviewer judges USEFUL / NEUTRAL / HARMFUL
```

这是低成本价值检查，不要求 full-trace human gold。若长期为 NEUTRAL/HARMFUL，Phase C
可 PARKED，不继续建设 journal correctness 体系。

2026-09-05 执行结果：三个最终 case 均由独立 reviewer 判为 `USEFUL`。其中 zero-Skill 的
第一次成功输出因丢失仍有效旧事实且 Event 证据不足被判为 `HARMFUL`；随后修复通用
full-field replacement 合同、补齐实际 Codex 配置观察并重跑，修正版通过。该轨迹完整保留在
`MILA_EVENT_RECONCILIATION_PHASE_C0_SPIKE_REPORT_20260905_013327.md`。

终态：

```text
PASS_EVENT_RECONCILIATION_VALUE_SIGNAL
```

它只证明值得提出 C1 最小持久化边界，不证明通用模型效果，也不自动授权 migration。

### C1 Simple Event journal

第一版逻辑结构：

```yaml
HostExecutionEvent:
  id: server-owned
  position: monotonic watermark
  task_ref: server-bound
  event_family: string
  event_type: string
  observed_at: timestamp
  evidence_refs: []
  bounded_payload: {}
```

真实表仍必须带 tenant/principal/project binding、created_at 与最小审计字段。`event_family`
与 `event_type` 使用可扩展词汇，不做封闭数据库 enum。

Starter vocabulary：

| event_family | event_type | 说明 |
| --- | --- | --- |
| `DIALOGUE` | `MESSAGE` | 指向 Host-visible user/assistant Evidence |
| `EXECUTION` | `FILES_CHANGED` | checkpoint window 内去重文件集合 |
| `EXECUTION` | `TEST_RESULT` | 重要失败/通过 transition |
| `EXECUTION` | `COMMAND_FAILURE` | 有任务影响的命令失败 |
| `GIT` | `COMMIT` | Host 观察到的 commit identity |
| `LIFECYCLE` | `SESSION_BOUNDARY` | checkpoint boundary，不单独制造 dirty |

2026-09-05 实施结果：已以 `0051_host_execution_event` 完成 reversible migration、内部
append/window REST、RLS、append-only、Evidence ref 在线失效、绑定命名空间幂等与一致读取。
最终 fresh-database gate 为 `922 passed, 1 skipped`，三类独立 subagent review 均为 PASS。
Public `codex-full` 仍为 13 tools。

终态：

```text
PASS_SIMPLE_EVENT_JOURNAL
```

### C2 Sparse observation adapters

MiLA core 保持 host-agnostic。Codex adapter 负责将 file/test/command/git/dialogue 观察聚合为
稀疏事件；Web、IDE 或其他 Agent Host 可以提供自己的 adapter。

禁止：

- 逐行文件写入全部记 Event；
- 每个成功 `ls`/read 都写 Event；
- 在 Event 中复制 raw dialogue 或 hidden chain-of-thought；
- Host 预先判断 requirement/decision/hypothesis 语义。

2026-09-05 实施结果：Host hook 在显式 `SHADOW` 下可将 user/assistant dialogue
Evidence 与 session boundary 写入 C1 journal。对话 Event 只包含 exact Evidence ref、role 与时间；
高频 tool/artifact observation 在聚合器实现前不写 journal。Python client 173 tests、hooks
17 tests 全部通过，真实 HTTP/PostgreSQL happy path 与整链 replay 均通过。

终态：

```text
PASS_MINIMAL_SPARSE_OBSERVATION_ADAPTER
```

### C3 Minimal StateDelta

Codex 只输出有限字段操作：

```text
missing field = KEEP
REPLACE       = replace one semantic field
CLEAR         = explicitly clear one semantic field
```

不开放 arbitrary JSON Patch。Host deterministic validate/merge 后，将完整 payload 通过现有
Working State CAS 写入。

2026-09-05 实施结果：纯 Host-side primitive 已实现 exact base 验证、有限字段
KEEP/REPLACE/CLEAR、frozen-window Event reference validity、full payload merge 与 effective no-op
拒绝。Merge result 携带精确 base ID/version 供后续 CAS；未调用模型或数据库。Hooks 34 tests
、Ruff、mypy 与 build 全部通过。

终态：

```text
PASS_MINIMAL_STATE_DELTA_VALIDATE_MERGE
```

### C4 Checkpoint / Resume reconciliation

Host 只决定 WHEN：

```text
unreconciled change candidate exists
AND
session end / task switch / pause / compaction / bounded threshold
  -> reconciliation opportunity
```

Codex 决定 WHAT CHANGED。失败时不推进 basis，不伪装 FRESH；interactive coding 默认可携带
`STALE_PENDING_RECONCILIATION` 状态继续，避免 memory subsystem 成为单点故障。

2026-09-05 实施结果：新增内部显式 `milai-hook ReconcileState`，由 Host 传入 Codex-produced
Delta；command 重读 exact TASK State 与完整 Event window，校验 Codex 所见 high watermark，
再执行 C3 merge 与 Working State CAS。No-material 不写；晚到 Event、cursor 超前、ineligible
Evidence ref、State/CAS conflict 均不会返回假成功。Runtime operation ID 已按 principal/project/
task namespace。真实 PostgreSQL/HTTP 完成 ABSENT→V1、no-material、late-window reject、V1→V2
及同公共 operation ID 跨两 task 独立 V1。Hooks 52 tests，三类 subagent 最终均 PASS。

终态：

```text
PASS_EXPLICIT_RECONCILIATION_ORCHESTRATION
```

### C5 Real cross-session tasks

至少用多条真实连续任务链观察：

- delta 是否保留有价值的 goal/decision/blocker/failed approach/next action；
- stale state 是否能被纠正；
- repeated failure 是否下降；
- resume 是否更快；
- Working State 是否保持 non-canonical。

本阶段采用 Engineering Mode；若要声明模型效果，再单独开启 Research Mode。

2026-09-05 执行结果：两个独立 TASK chain、六个 fresh zero-Skill Codex Session 均在推理前
得到 ACTIVE Working State，并实际使用其中的 next action。Chain A 连续保留并修正 package
runner、uv cache 与 pytest capture 三次失败，最终 focused regression `1 passed`；Chain B
清除 POST-not-retry hypothesis，将 read-only-only blocker 修正为 managed-sandbox boundary，
并由 unrestricted Codex 独立复现 Host 的 `1 passed`。两条 State chain 均从 V1 走到 completed
V4，Canonical mutation 为 0。

终态：

```text
PASS_REAL_CROSS_SESSION_USEFULNESS_ENGINEERING_SIGNAL
```

该结论不外推为自然 adoption 或模型效果；完成凭据见
`MILA_EVENT_RECONCILIATION_PHASE_C5_COMPLETION_REPORT_20260905.md`。

## 15. Phase D — Retrieval Evolution

Retrieval workstream 与 Cognitive State 保持独立：

- Product-11 stateful persisted-frontier continuation；
- explicit intra-source turn acquisition；
- high-precision historical prefetch；
- cumulative evidence completeness；
- Codex-controlled residual continuation。

Retrieval effect claim 使用 sealed development slice 和预注册指标。不得将 retrieval failure
归因成 Working State failure，也不得让 Cognitive State 承担 retrieval frontier。

2026-09-05 D1 实施结果：新增独立 immutable `RetrievalContinuationState`、基础 migration
`0052_retrieval_continuation` 与 hardening migration `0053_continuation_hardening`；Call 1 保持原
selection/compiler，Call 2 只恢复 exact persisted frontier，并在线重验 principal/scope、retention、
revocation 与 content identity。数据库 successor 幂等不依赖 transport request ID，public MCP
input 不变。unknown locator 不退化为 fresh retrieval；不同 authenticated edge principal 在共享内部 reader
credential 下仍隔离。完整 Runtime、fresh PostgreSQL、真实 Streamable HTTP MCP、Python client 与
候选部署均通过。

Continuation render 显式关闭 adjacent hydration；Call 2 的 selected Evidence 必须是 predecessor
frontier 的子集。root 创建后才投影的同 Session neighbor 也不能越过该边界。

D1 只持久化候选 frontier，没有 official route-exhaustion receipt；因此候选池耗尽只返回
`PERSISTED_FRONTIER_EXHAUSTED`，在线 eligibility 变化返回 `FRONTIER_ELIGIBILITY_CHANGED`，不冒充
`FRONTIER_EXHAUSTED`。

终态：

```text
PASS_PERSISTED_FRONTIER_CONTINUATION_ENGINEERING_BASELINE
```

该终态不声明 P11-C1 coverage/effect。

2026-09-05 D2 实施结果：新增 migration `0054_intra_source_shadow` 与 lexical-only SHADOW service。
Runtime 将 official coarse Evidence 的 exact IDs 交给 PostgreSQL；数据库完成 live governance 与
content-identity 重验后推导 `(source_type, source_session_id)`，只在该结构化池内检索 turn。候选
上限固定为 50 sources/sessions、8 hits/source、120 total，正文不进入 trace，fine candidates 不进入
Context 或 persisted frontier。候选部署以 `SHADOW` 启用，public MCP input/catalog 不变。

终态：

```text
PASS_EXPLICIT_INTRA_SOURCE_ACQUISITION_SHADOW_ENGINEERING_BASELINE
```

该终态不声明 P11-C2 coverage/effect；Dense、FRONTIER 与 renderer integration 仍需 Research X0
及预注册 effect gate。

## 16. Phase E — Optimization / Hardening Backlog

以下内容保留，但不再作为 Phase A-C 的默认前置条件：

- journal epoch 与完整 replayability proof；
- retention gap、exact identity loss 与所有 Basis gap failure；
- late-event 完整并发语义；
- dirty class threshold 与自适应 batching；
- 多级 freshness 状态；
- 完整 failure-injection matrix；
- semantic grounding benchmark 与人工 adjudication；
- large-scale retention、性能、压缩和清理；
- Formal holdout 与对外算法 claim。

仅在满足至少一个条件时提升为当前开发项：

1. 真实使用出现可复现 failure；
2. 当前 Milestone 验收指标无法满足；
3. Research Mode claim 明确需要；
4. 外部合规、数据保留或 release requirement 明确要求。

## 17. Feature First, Hardening Second

以 Event reconciliation 为例：

```text
V0
  sparse Event + old State
    -> Codex Delta
    -> useful new State

V1
  production binding + CAS + scope + refs

V2
  only when evidence requires:
  late events / epoch / replayability / retention-gap hardening
```

禁止先完成 V2，再验证 V0 是否具有产品价值。

## 18. Failure Reflection Loop

每次失败按以下循环处理：

```text
reproduce
  -> isolate owning layer
  -> identify smallest current failure
  -> implement smallest general fix
  -> focused test
  -> real E2E
  -> regression
  -> record residual risk
```

若首次修复失败，检查假设、trace 与 owner；仍无法定位时才提高推理/审查强度。不能用更多
schema、prompt、state type 或 hidden Reader 掩盖未知根因。阻塞项不妨碍推进互不依赖的
Milestone 工作。

## 19. 测试金字塔

### Unit

- schema validation；
- operation fingerprint/idempotency；
- CAS conflict；
- bounded bootstrap；
- delta KEEP/REPLACE/CLEAR；
- scope binding。

### Integration

- real PostgreSQL persistence；
- RLS/cross-scope isolation；
- revoke-first read behavior；
- Proposal/Review/ClaimVersion lifecycle；
- State restart persistence。

### HTTP MCP E2E

- initialize/tools/list；
- structured tool call/results；
- auth failure 与 valid credential；
- full read/write/govern/revoke/state lifecycle；
- remote-client registration shape。

### Real-use

- MCP-only Codex tasks；
- cross-session resume；
- reconciliation usefulness；
- Product-11 retrieval opportunities。

## 20. 各阶段主要指标

### Phase A

```text
LifecycleStepPassRate
OperationRetryDuplication
CrossScopeLeak
RevokedEvidenceValidRead
RecallCanonicalMutation
```

### Phase B

```text
ResumePrefetchSuccessRate
BootstrapStateUsefulRate
TimeToFirstUsefulAction
UnnecessaryPrefetchRate
```

### Phase C

```text
StateDeltaUsefulness
MaterialStateUpdateRate
StaleStateCorrectionRate
RepeatedFailureRate
ReferenceValidityRate
```

`ReferenceValidityRate` 只表示 ref 存在、可读、属于窗口且 scope 正确，不声称语义 grounding。
语义正确性属于 reviewer 或 Research Mode scorer。

### Phase D

沿用 Product-11 预注册的 continuation、direct acquisition、duplicate 与 cumulative coverage
指标，不与 Phase C 指标混合。

## 21. Milestone Completion Report

每个 Milestone 只输出一次收口报告：

```yaml
milestone:
status: PASS | PARTIAL | PARKED
goal:
implemented:
real_e2e:
tests:
hard_invariants:
review_decision:
required_fixes_resolved:
known_limitations:
deferred_hardening:
next_milestone:
```

审计记录默认自动写入现有审计面；自动审计不等于自动获得 mutation、review、revoke 或 cleanup
authority。

## 22. 当前阶段与下一步

```text
Phase A  Memory MCP Baseline
  PASS_MEMORY_MCP_FUNCTIONAL_BASELINE

Phase B  Host Continuity
  PASS_HOST_CONTINUITY_MINIMAL_BASELINE

Phase C  Event Reconciliation
  PASS_EVENT_RECONCILIATION_VALUE_SIGNAL
  PASS_SIMPLE_EVENT_JOURNAL
  PASS_MINIMAL_SPARSE_OBSERVATION_ADAPTER
  PASS_MINIMAL_STATE_DELTA_VALIDATE_MERGE
  PASS_EXPLICIT_RECONCILIATION_ORCHESTRATION
  PASS_REAL_CROSS_SESSION_USEFULNESS_ENGINEERING_SIGNAL

Phase D  Retrieval Evolution
  PASS_PERSISTED_FRONTIER_CONTINUATION_ENGINEERING_BASELINE
  PASS_EXPLICIT_INTRA_SOURCE_ACQUISITION_SHADOW_ENGINEERING_BASELINE
  RESEARCH_EFFECT_BLOCKED_X0

Phase E  Optimization / Hardening
  BACKLOG_TRIGGERED_BY_EVIDENCE
```

Phase A 已于 2026-09-05 完成：真实 PostgreSQL lifecycle、公网候选 endpoint、无 Skills 的
Codex MCP-only 使用、完整回归和三类独立 subagent boundary review 均通过，required fixes 为 0。
完成凭据见 `MILA_MEMORY_MCP_PHASE_A_COMPLETION_REPORT_20260905_010632.md`。

Phase B 已于 2026-09-05 完成：Host 在 Codex 推理前确定性 GET，精确校验并注入 bounded
non-canonical bootstrap；两个显式关闭 Skills 的新 Session 恢复了旧 State，其中一个执行了
未在新 prompt 中指定的真实只读代码 next action。三类 subagent review 均 PASS，required
fixes 为 0。完成凭据见 `MILA_HOST_CONTINUITY_PHASE_B_COMPLETION_REPORT_20260905_011438.md`。

Phase C0 已于 2026-09-05 完成：最终 value set 为 proxy diagnosis、zero-Skill evidence
correction v2 与 nested Evidence scope repair，三项均为 `USEFUL`；机械引用/字段边界通过，三类
subagent review 无未解决 hard finding。完成凭据见
`MILA_EVENT_RECONCILIATION_PHASE_C0_SPIKE_REPORT_20260905_013327.md`。

Phase C1 已于 2026-09-05 完成：最小 Event journal 在真实 PostgreSQL 上通过 append、
window、retry、binding isolation、revocation ref invalidation、migration round-trip 与并发 snapshot 验证。
独立审查最初发现的 window 并发不一致和幂等键 namespace 冲突已修复，复核均 PASS。
完成凭据见 `MILA_EVENT_RECONCILIATION_PHASE_C1_COMPLETION_REPORT_20260905.md`。

Phase C2 已于 2026-09-05 完成：真实 Host hook 完成 Evidence 先行、exact ref 稀疏 Event
写入与整链幂等 replay。静态配置在任何写入前验证，动态 journal failure 返回可解释的
partial receipt。三类 subagent review 均 PASS。完成凭据见
`MILA_EVENT_RECONCILIATION_PHASE_C2_COMPLETION_REPORT_20260905.md`。

Phase C3 已于 2026-09-05 完成：有限字段 Delta 在纯函数层完成 base、operation、Event ref
与 effective-change 验证，生成保留未改字段的新 full payload。三类 subagent review 均 PASS。
完成凭据见 `MILA_EVENT_RECONCILIATION_PHASE_C3_COMPLETION_REPORT_20260905.md`。

Phase C4 已于 2026-09-05 完成：trusted Host command 将 exact State/Event window、Codex-produced
Delta 与现有 Working State CAS 接成真实闭环；no-material 不写，晚到 Event 不误推进，公共
operation ID 跨 task 隔离。两条真实 PostgreSQL/HTTP E2E 与三类 subagent 复核均 PASS。
完成凭据见 `MILA_EVENT_RECONCILIATION_PHASE_C4_COMPLETION_REPORT_20260905.md`。

Phase C5 已于 2026-09-05 完成：两个真实只读 coding task chain、六个 fresh zero-Skill
Codex Session 全部通过 Host prefetch 恢复 State；跨 Session next action 被实际执行，failed
approach 没有被无意识重复，stale hypothesis 被清除，blocker 被修正后解除。受管 sandbox
中的 asyncio test hang 被隔离为环境边界，正常 Host 与 unrestricted Codex 均通过；未为该环境
差异修改产品代码。完成凭据见
`MILA_EVENT_RECONCILIATION_PHASE_C5_COMPLETION_REPORT_20260905.md`。

Phase D1 已于 2026-09-05 完成并经 `0053` hardening：same-query `previous_context_id` 只恢复
persisted frontier，第二次调用的 global reacquisition、candidate-pool extension 与 query replanning
均为 0，adjacent hydration 也为 0；真实 PostgreSQL 与 55-Evidence Streamable HTTP E2E 证明第二页
exact Evidence 与第一页无重叠，并证明两个 authenticated edge principal 的 state isolation。公网
7968 MCP 保持 13-tool catalog 与原 input schema，API/MCP 服务 active。完成凭据见
`MILA_PRODUCT-11_PHASE_D1_CONTINUATION_COMPLETION_REPORT_20260905.md`。

Phase D2 已于 2026-09-05 完成：exact coarse Evidence ID 在数据库内重验并推导
`(source_type, session_id)`；lexical fine candidates 只写 SHADOW diagnostic，不进入 Context/frontier。
Fresh PostgreSQL、完整 Runtime/MCP/client 回归、候选部署与三类 subagent review 均 PASS。完成凭据见
`MILA_PRODUCT-11_PHASE_D2_INTRA_SOURCE_SHADOW_COMPLETION_REPORT_20260905.md`。

当前增量动作：

1. 保持 D2 SHADOW，收集真实使用中的 candidate/latency/payload failure；
2. 只有 Research X0 真实通过后，才运行 P11-C1/C2 effect 并决定是否进入 FRONTIER；
3. 没有真实 failure 时不提前实现 Dense、epoch/replayability、复杂 trace store 或 renderer treatment；
4. 不让 Cognitive State 承担 retrieval frontier，也不修改 Canonical/Reader。

Phase C1 没有自动 checkpoint、没有把人工 adjudication 设为开发依赖，也没有消费 Product-11
Formal holdout。Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。

## 23. 相关工件

| 工件 | 作用 |
| --- | --- |
| `docs/contracts/MILA_HOST_COGNITIVE_STATE_CONTRACT.md` | Working State authority/persistence contract |
| `docs/contracts/MILA_MEMORY_ACTIVATION_POLICY_V1.md` | AUTO/HOST/EXPLICIT policy |
| `docs/goals/MILA_MEMORY_ACTIVATION_LAYER_设计开发规划.md` | Activation 目标架构参考 |
| `docs/goals/MILA_EVENT_GROUNDED_HOST_COGNITIVE_STATE_RECONCILIATION_设计开发规划.md` | Reconciliation/Hardening 参考 |
| `docs/adr/ADR-034-host-cognitive-affordance-layer.md` | Cognitive State 架构决策 |
| `docs/adr/ADR-039-host-managed-memory-activation.md` | Host-managed activation 决策 |
| `docs/goals/MILA_MEMORY_MCP_PHASE_A_COMPLETION_REPORT_20260905_010632.md` | Phase A 功能基线完成凭据 |
| `docs/goals/MILA_HOST_CONTINUITY_PHASE_B_COMPLETION_REPORT_20260905_011438.md` | Phase B Host continuity 完成凭据 |
| `docs/goals/MILA_EVENT_RECONCILIATION_PHASE_C0_SPIKE_REPORT_20260905_013327.md` | Phase C0 value-signal 完成凭据 |
| `docs/goals/MILA_EVENT_RECONCILIATION_C1_MINIMAL_SCHEMA_BOUNDARY_PROPOSAL_20260905.md` | C1 最小持久化边界与实施范围 |
| `docs/goals/MILA_EVENT_RECONCILIATION_PHASE_C1_COMPLETION_REPORT_20260905.md` | C1 完成凭据与 failure reflection |
| `docs/goals/MILA_EVENT_RECONCILIATION_PHASE_C2_COMPLETION_REPORT_20260905.md` | C2 sparse adapter 完成凭据 |
| `docs/goals/MILA_EVENT_RECONCILIATION_PHASE_C3_COMPLETION_REPORT_20260905.md` | C3 StateDelta 验证/合并完成凭据 |
| `docs/goals/MILA_EVENT_RECONCILIATION_PHASE_C4_COMPLETION_REPORT_20260905.md` | C4 显式 orchestration 完成凭据 |
| `docs/goals/MILA_EVENT_RECONCILIATION_PHASE_C5_COMPLETION_REPORT_20260905.md` | C5 真实跨 Session usefulness 完成凭据 |
| `docs/goals/MILA_PRODUCT-11_PHASE_D1_CONTINUATION_COMPLETION_REPORT_20260905.md` | Phase D1 persisted-frontier continuation 完成凭据 |
| `docs/goals/MILA_PRODUCT-11_PHASE_D2_INTRA_SOURCE_SHADOW_COMPLETION_REPORT_20260905.md` | Phase D2 explicit intra-source SHADOW 完成凭据 |
| `docs/goals/MILA_MEMORY_MCP_FUNCTIONAL_BASELINE_V1.md` | 当前冻结的工程功能基线与变更准入 |
| `docs/reports/MILA_PRODUCTION_FAILURE_LEDGER.md` | 真实任务失败分类与后续 Goal 入口 |
| `docs/reports/MILA_MEMORY_PERFORMANCE_BASELINE_V1_20260905.md` | 初始只读部署成本与待自然采集指标 |
| `docs/goals/artifacts/phase-c0/` | C0 frozen inputs、schemas 与 exact Codex outputs |
| `docs/goals/artifacts/phase-c1/runtime-full-gate-final.json` | C1 fresh PostgreSQL full-gate 凭据 |
| `integrations/mcp/src/milai_mcp/server.py` | HTTP MCP server/tool catalog |
| `integrations/mcp/src/milai_mcp/launcher.py` | Codex launcher/continuity integration |
| `runtime/migrations/versions/0050_host_cognitive_state.py` | 已有 Working State persistence |
| `runtime/migrations/versions/0051_host_execution_event.py` | C1 append-only Event journal |
| `runtime/migrations/versions/0052_retrieval_continuation_state.py` | D1 append-only RetrievalContinuationState |
| `runtime/migrations/versions/0053_retrieval_continuation_hardening.py` | D1 principal/identity/replay/resource hardening |
| `runtime/migrations/versions/0054_intra_source_lexical_shadow.py` | D2 governed lexical fine-acquisition SHADOW |

## 24. Product 状态

```text
Schema            0.1.x EXPERIMENTAL
Implementation    CANDIDATE
Release posture   NO-GO FOR SCHEMA FREEZE
Formal 500        NOT CONSUMED BY THIS PLAN
Reader / vLLM     NOT INTRODUCED
```

v1.1 的成功标准不是一次完成最终架构，而是按顺序交付可用产品闭环，并让每一层新增复杂度都由
真实失败、明确指标或 Research claim 支持。
