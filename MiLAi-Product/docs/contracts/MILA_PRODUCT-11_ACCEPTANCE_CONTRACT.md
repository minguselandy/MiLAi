# Product-11 验收合同：Explicit Acquisition 与 Non-Destructive Continuation

状态：`FROZEN RESEARCH GATES / D1+D2 ENGINEERING IMPLEMENTED / EFFECT GATED BY X0`  
版本：`v0.2`  
日期：`2026-09-05`  
依据：`MILA-PRODUCT-11@0.3`、`ADR-032 ACCEPTED`

## 1. 合同用途

本合同把 Product-11 的 X0--X4、数据库状态、trace、指标、失败预算与终态变成可直接测试的事实。
任何实现成功、单测通过或单 case gain 都不能替代 effect gate。

Engineering note：D1 persisted-frontier continuation 与 D2 lexical intra-source SHADOW 已完成，
但不改变本合同的 X1/X2 effect 阈值。D2 当前只接受 `OFF | SHADOW`，使用 exact coarse Evidence ID
在数据库内推导 `(source_type, session_id)`；SHADOW candidate 不进入 Context/frontier，不能计入
Research numerator。

## 2. 不可变输入与 anti-leakage

每个 effect run 在 treatment 前写入不可覆盖 preseal：

```yaml
run_id:
block: X0 | X1 | X2 | X3_0 | X3_1 | X4
arm:
product_tree_sha256:
product_lock_digest:
lab_tree_sha256:
lab_runner_sha256:
command_sha256:
dataset_sha256:
selection_sha256:
human_label_sha256:
human_annotator_id:
independent_reviewer_id:
adjudication_receipt_sha256:
case_order_sha256:
source_snapshot_as_of:
profile: MCP_INTERACTIVE_WIDE_V01
dense_model_identity: null | object
formal_files_accessed: false
formal_cases_scored: 0
```

Product request、environment、trace 和 MCP payload 中以下 key/value 的出现次数必须为 0：

```text
case_id / benchmark_id used for routing
reference_answer / expected_answer / gold_quote
instance_group / group_id / acceptable_evidence_ids / acceptable_turn_refs
human adjudication decision
LLM-generated instance_key / count / set_members
```

Lab 只有在 immutable Product trace 写盘并校验 digest 后才能加载 human label。

## 3. X0 seal contract

### 3.1 数据边界

- 使用全新的 `OPENED_DEVELOPMENT_ONLY` Product-11 slice；
- 不读取、抽样或派生 `longmemeval-s-cleaned-500` Formal 500；
- Product-10 Qwen proxy label 不可复制为 gold；
- 至少 24 case，capability shape 每类至少 3；
- continuation 与 intra-source opportunity 各至少 8；control/already-complete 至少 8；类别可重叠。

### 3.2 人工确认

每个 case 必须有一名真实 annotator 与一名不同身份的独立 human reviewer。模型输出只能标为
`model_assisted_proxy=true`、`human_adjudication_status=PENDING`。最终 seal 必须：

```text
human_adjudication_status               COMPLETE 100%
annotator_id != reviewer_id              100%
unresolved disagreements                  0
required groups                           >0 per case
acceptable Evidence/turn refs             >0 per required group
acceptable_evidence_id cross-group overlap 0
acceptable_turn_ref cross-group overlap    0
source/session cross-group overlap         allowed
```

opportunity membership 由 A0 sealed trace 与 human label 离线 join；不得靠 treatment outcome 重选。

### 3.3 X0 出口

所有门满足才可写 `PASS_PRODUCT11_X0_HUMAN_SEAL`。否则 Product behavior/migration 继续禁止。case 或
opportunity 不足时才可使用终态 `PARKED_PRODUCT11_INSUFFICIENT_HUMAN_SEALED_OPPORTUNITY`；仅缺人工
签署时记 `X0_AWAITING_HUMAN_ADJUDICATION`，不能伪装成机会不足。

## 4. `RetrievalContinuationState` domain contract

### 4.1 Root state

root 在 first call 的 official acquisition 内形成，包含：

```text
same tenant/principal/project/scope/authority/consistency
fixed snapshot_as_of + canonical_position
original_query_hash
route_plan_digest + frontier_digest
ordered candidate refs or sealed resumable route cursors
seen anchor Evidence IDs + seen rendered turn IDs/source spans
budget history
created/expires/state digest
```

first-call public Evidence projection 相对 frozen A0 必须完全一致；只允许 opaque context/trace ID、
latency 与已证明 continuation assertion 不同。

### 4.2 Successor idempotency

```text
operation_fingerprint = SHA256(canonical_encode(
  predecessor_state_id,
  predecessor_generation + 1,
  query_hash,
  principal_binding_digest,
  scope_digest,
  root_snapshot_as_of,
  payload_semantics_version
))
```

必须直接验证：

| Case | Expected |
| --- | --- |
| same predecessor + same semantic payload, different request IDs | same successor state ID |
| concurrent same fingerprint | one row, every caller receives same successor |
| same predecessor + different residual query | distinct explicit branch |
| predecessor/generation/root digest mismatch | fail closed |
| attempted successor semantic update | rejected |

### 4.3 Profile resource limits

```text
frontier refs/state   <=120
generation            <=4
successors/state      <=8
states/root           <=16
serialized state      <=262144 bytes
```

每个限制都有 direct boundary test（at limit accepted；limit+1 typed failure）。不得截断，所有失败
reason 不等于 `FRONTIER_EXHAUSTED`，模型不能覆盖这些限制。

## 5. X1 persisted-frontier-only contract

### 5.1 Arms

```text
A0-FRESH2
  Call1 frozen A0
  Call2 same query, no previous_context_id

A1-STATEFUL primary
  Call1 semantically identical to A0 and seals frontier
  Call2 same query_hash + previous_context_id
  global reacquisition=0
  candidate-pool extension=0
  query replanning=0
  output origin=PERSISTED_FRONTIER only

A1R-RESIDUAL secondary
  presealed residual query + previous_context_id
  new candidates origin=RESIDUAL_ACQUISITION
```

从 root state 已持久化 route/cursor predecessor 继续取下一页可归为 `PERSISTED_FRONTIER`；新增 route
或重新执行 global source search 不可。

### 5.2 Required trace

每个 continuation candidate：

```yaml
candidate_origin: PERSISTED_FRONTIER | RESIDUAL_ACQUISITION
origin_state_id:
origin_frontier_digest:
origin_route:
origin_cursor_before:
origin_cursor_after:
evidence_id:
turn_or_span_ref:
content_hash:
online_revalidation:
seen_exclusion_disposition:
```

trace 另记录 global acquisition call count、route-plan digest before/after、candidate-pool cardinality
before/after、Reader/vLLM/retry count 与 Canonical mutation count。

### 5.3 X1 gates

```text
paired cases                                      >=24
continuation opportunity cases                    >=8
FirstCallEvidenceProjectionDigest match           100%
FirstCallDistinctInstanceCoverage delta            0
previously full first-call cases lost              0
mean ContinuationInstanceGain                     >=+0.15 macro
ContinuationOpportunityRecoveryRate               >=50% case-level
A1 Call2 PERSISTED_FRONTIER candidates             100%
A1 Call2 global reacquisition calls                 0
A1 Call2 candidate-pool extensions                  0
A1 Call2 adjacent hydration calls                   0
exact seen Evidence repeats                         0
exact seen rendered-turn repeats                    0
DuplicateInstanceRate(A1)                          <=A0-FRESH2 macro
principal/scope/snapshot/revocation violations      0
Canonical/Reader/vLLM/semantic retries              0/0/0/0
```

A1R 任何结果不得进入上述 primary numerator/denominator。

## 6. Continuation assertion truth table

| Proven Runtime state | Public assertion |
| --- | --- |
| current state persisted/resumable；online revalidation 后存在 eligible item | `{available:true, reason:UNSEEN_EVIDENCE_FRONTIER}` |
| current query lineage 已执行 official routes 均有 exhaustion receipt | `{available:false, reason:FRONTIER_EXHAUSTED}` |
| D1 persisted candidate pool consumed；无 official route receipt | `{available:false, reason:PERSISTED_FRONTIER_EXHAUSTED}` |
| remaining candidate 因 permission/retention/revocation/content identity 在线变化失效 | `{available:false, reason:FRONTIER_ELIGIBILITY_CHANGED}` |
| call budget used but frontier may remain | `{available:false, reason:CALL_BUDGET_EXHAUSTED}` |
| any state resource limit hit | matching typed limit reason, never `FRONTIER_EXHAUSTED` |
| persistence/identity/snapshot/exhaustion cannot be proven | `null` + typed warning |
| unknown/not-owned/expired/tampered | uniform fail-closed response, no old Evidence |

测试必须明确断言 `FRONTIER_EXHAUSTED` 不产生 semantic completeness、corpus exhaustion 或“无需
residual query”字段。

D1 只实现后两种 candidate-level reason；在 route receipt 尚未持久化前，D1 不得返回
`FRONTIER_EXHAUSTED`。

## 7. X2 explicit intra-source acquisition contract

### 7.1 Matched arms

```text
B0-OFFICIAL
  current direct anchors; adjacent turns HYDRATION_ONLY

B1-LEXICAL-SHADOW
  exact same coarse source/session pool + lexical turn/span retrieval

B2-LEXICAL-DENSE-SHADOW
  B1 + frozen Dense turn/span retrieval
```

三臂必须共享 coarse pool exact identities、order、scope、snapshot 和 fixed resource envelope。SHADOW
不能改变 Context/first-call response。B1 满足 gate 时不执行装饰性 B2。

### 7.2 Fine candidate contract

```text
source_id/session_id/turn_or_span_id/evidence_id/content_hash required
scope_digest/snapshot_as_of/decision_digest required
acquisition_channels/channel_ranks required
hard dedup exact stable identity only
new global source acquisition 0
fine lexical hits/source <=8
fine Dense hits/source <=8
fine unique candidates <=120 total
```

trace discovery disposition 只允许 `DIRECT_ANCHOR` 或 `HYDRATION_ONLY`。Hydration 不能创建 frontier、
不能算 direct coverage、不能提升 authority。

### 7.3 X2 gates

```text
paired cases                                      >=24
intra-source opportunity cases                    >=8
coarse source/session pool exact match             100%
mean DirectAcquisitionCoverageGain                >=+0.10 macro
IntraSourceOpportunityRecoveryRate                >=50% case-level
NewDirectRequiredGroups                           >=4 group count
gain capability shapes                            >=2
LostDirectRequiredGroups                           0
cross-source hard identity collapse                0
hydration credited as direct discovery             0
scope/snapshot/permission violations               0
```

Dense 被选择时必须封存真实 model/revision/index/config digest；否则只能报告 lexical-only。

## 8. X3 integration contract

进入条件严格为：

```text
X1-C1 == PASS
AND X2-C2 == PASS
AND selected minimal X2 variant is sealed
else X3=NOT_ENTERED
```

X3-0 只把 fine candidate 放入 frontier，first-call A0 digest 必须保持。X3-1 先渲染全部 admitted
direct anchors，再以剩余预算 hydration。判门：

```text
baseline direct anchors retained                   100%
previously full first-call cases lost              0
hydration counted as direct discovery              0
DIRECT_ANCHOR required group demoted to HYDRATION_ONLY 0
anchor evicted by hydration                        0
first-call tokens                                  16384 unchanged
continuation exact-seen repeat                      0
cumulative coverage                                >=selected X1
safety/Canonical violations                        0
```

`HydrationOnlyRequiredGroups` 必须报告但不要求为 0。X3-1 失败时保留 X3-0，renderer flag OFF。

## 9. Metric scorer contract

所有主 gain 使用 opportunity case macro mean：

```text
DIC_i(S) = covered_required_groups_i(S) / required_groups_i
ContinuationInstanceGain = mean_i(DIC_i(Call1∪Call2)-DIC_i(Call1))

DAC_i(A) = directly_acquired_required_groups_i(A) / required_groups_i
DirectAcquisitionCoverageGain(Bx) = mean_i(DAC_i(Bx)-DAC_i(B0))
```

case-level recovery rate、group-level new/lost count 分别计算，绝不互换。duplicate：

```text
n_i,g(A) = count of cumulative visible exact units human-mapped to required group g
DIR_i(A) = sum_g max(0,n_i,g(A)-1) / sum_g n_i,g(A)
DuplicateInstanceRate(A) = macro mean DIR_i over non-zero-denominator eligible cases
```

零分母为 `NA`，不注入 0。human mapping 仅在 immutable trace 完成后由 scorer 加载。

## 10. Fresh PostgreSQL / safety matrix

必须使用 fresh database 直接验证：

| Case | Expected |
| --- | --- |
| same tenant/principal/project/scope | owned state visible |
| other actor same tenant | uniform not-owned/no leakage |
| other tenant | RLS isolation |
| narrowed/broadened scope | digest mismatch/no continuation |
| root snapshot/canonical position drift | fail closed |
| expired state | unavailable/no old Evidence |
| revoked/unreadable Evidence | candidate removed, text absent |
| content hash changed | candidate rejected |
| subject deletion/tenant cleanup | state and references removed/expired |
| DB unavailable | no in-memory persistence fallback |
| recall execution | Canonical/Claim/OpenIssue mutation count 0 |

migration 必须从当前 chain head 前向升级；不得改写 0001--0049。PUBLIC 无 procedure 权限。

## 11. MCP/public compatibility

`milai_memory_resolve` input property set 必须仍为：

```json
["previous_context_id", "query"]
```

Host prompt、MCP model-controlled budget/scope 参数、Reader API 与 Canonical schema 均不改变。
authenticated Streamable HTTP smoke 必须覆盖 first call、stateful second call、unknown/not-owned ID 与
typed assertion forwarding。

## 12. X4 attribution

仅对 treatment outcome 前封存、且 cumulative memory coverage=1 的最多 8 case 运行 real Codex HTTP。
无 vote、无 semantic retry、无 Host prompt treatment。分类优先级：

```text
MiLA cumulative Evidence incomplete      MiLA failure
MiLA complete / Host retained incomplete Host context-integration failure
Host-visible complete / answer wrong     Memory PASS / Host aggregation FAIL
```

Host failure 不得触发 Reader、answer-oriented prompt 或 instance/count schema。

## 13. 修复预算、运行与终态

X1、X2 各只允许 initial general implementation + one preregistered general repair。每次 first loss 用一个
failure case、一个不同-shape sibling 和一个正确 regression 验证；保留 invalid/failed run，不覆盖。
X1 effect 失败仍可运行 X2；X3 必须两者都 PASS。

终态及优先级完全继承 Goal §16。每个 run 必须有唯一 run ID、preseal、Product/Lab/input hashes、
trace-before-label、fresh PostgreSQL 起点与 cleanup receipt。Formal 500 始终：

```text
formal_files_accessed = false
formal_cases_scored = 0
```

## 14. 当前执行状态

```yaml
authorization: GRANTED_2026-09-04T08:02:14+08:00
x0: ACTIVE_HUMAN_ADJUDICATION_REQUIRED
adr_032: ACCEPTED_IMPLEMENTATION_GATED
acceptance_contract: FROZEN
product_behavior: NOT_STARTED_X0_GATE
migration: NOT_STARTED_X0_GATE
opened_development_effect: NOT_STARTED
real_codex: NOT_ENTERED
formal_holdout: NOT_AUTHORIZED_UNCONSUMED
```
