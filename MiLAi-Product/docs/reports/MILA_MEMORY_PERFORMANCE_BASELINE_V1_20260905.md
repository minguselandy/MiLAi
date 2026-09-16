---
document_id: MILA-MEMORY-PERFORMANCE-BASELINE-V1
version: "1.1"
status: EXPANDED_REAL_AND_LME_ENGINEERING_BASELINE
measured_at: "2026-09-05T12:08:00+08:00"
product_tree_sha256: f998c2d96c6ae4a4e2ffa246d12257938af29a9e49c60f48ad21e7b50250cad1
---

# MiLA Memory Performance Baseline V1

## 1. 测量边界

这是候选部署的低成本观测基线，不是 SLO、benchmark effect 或容量证明。

```text
host                         deployed MiLA host
path                         loopback Runtime HTTP
mode                         sequential, read-only
warmup                       5 requests/path
measured samples             50 requests/path
MemoryResolve workload       unique negative-control lexical query
WorkingState workload        ABSENT TASK state GET
intra-source mode            SHADOW
skills / Codex reasoning     not involved
```

百分位使用 sorted nearest-rank：P50=`ceil(0.50*N)`，P95=`ceil(0.95*N)`。

## 2. 已测结果

| Operation | N | P50 | P95 | Mean | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `MemoryResolve` negative-control | 50 | 50.071 ms | 57.720 ms | 49.363 ms | 58.365 ms |
| `WorkingState GET` ABSENT | 50 | 4.047 ms | 4.780 ms | 4.060 ms | 6.063 ms |

这些结果只适用于本机 loopback、当前数据规模和上述负样本；不能外推公网延迟、hit workload 或并发
容量。

## 3. 暂不伪造的指标

| Metric | Current status | 采集条件 |
| --- | --- | --- |
| Continuation P50/P95 | `EXECUTED_7_TASKS_LATENCY_NOT_ISOLATED` | MCP call-level timer; current trace has Codex-process latency only |
| Reconciliation P50/P95 | `NOT_MEASURED` | 下一次真实 checkpoint/reconcile |
| Context/Evidence/Hydration tokens | `NOT_CAPTURED_BY_CURRENT_MCP_TRACE` | structured per-call token counters |
| Candidates examined/rendered | `PARTIAL_LME_RENDERED_ONLY` | examined count requires public bounded trace |
| Event writes/task | `MEASURED_LME_7_TASKS` | 3,419 total; mean 488.43; median 489; range 409–566 |
| State versions/task | C5 observed `4` in each of 2 chains; not a distribution | more real chains |
| Memory calls/successful task | `2.0_PER_GUIDED_DIAGNOSTIC_TASK`; success denominator not claimed | task-level outcome judgement |
| UsefulEvidenceTokens / MemoryContextTokens | `REQUIRES_TASK_OUTCOME_LABEL` | lightweight post-task judgement |

没有为了填表创建 synthetic State update、Event 或 Reconciliation mutation。一次 read-only
continuation probe 没有可用 frontier，因此如实记录为未测。

## 4. R1 real-use task samples

R1 Window 1 added two task-level observations; they are not latency percentiles:

| Task | Resolve calls | Outcome | Evidence | Codex input/output tokens |
| --- | ---: | --- | ---: | ---: |
| unavailable baseline history | 3 | correct abstention | 0 governed IDs | 92,851 / 456 |
| known retry-safety history | 1 | correct evidence-grounded answer | 8 units | 96,421 / 498 |
| post-fix unique-marker miss | 1 | correct bounded miss | 0 governed IDs | 65,507 / 258 |

The first direct public positive resolve observed before Codex orchestration took 240.910 ms after MCP
session initialization. One sample is not promoted to a public-network baseline. Codex input tokens
include Host/model/tool context and cache accounting, so they are not mislabeled as Memory Context
tokens or attributed to the 13-tool catalog without a paired isolation.

## 5. LME capture/projection and guided-continuation samples

Opened-development LME engineering diagnostics added two non-SLO observations. The representative
COUNT case captured 484 Events with eight workers:

| Phase | Wall time | Share of capture + wait + resolve |
| --- | ---: | ---: |
| Evidence capture | 21,916.423 ms | 93.05% |
| projection readiness tail wait | 951.302 ms | 4.04% |
| resolve | 685.880 ms | 2.91% |

The seven-task guided-continuation window then captured 3,419 Events and made exactly two MCP resolve
calls per task:

```text
capture total / P50 / P95       161,367.880 / 24,117.661 / 25,423.866 ms
projection wait total/P50/P95     2,877.573 /    386.880 /    963.156 ms
capture share of capture+wait         98.25%
projection tail-wait share             1.75%
rendered Evidence units                 266 across 14 calls
serialized turn refs                    392 across 14 calls
novel second-page turn refs              152
required-turn gain after Call 1            0
```

Projection work overlaps capture; readiness measures only the remaining consistency barrier, not
total worker CPU. Projection is required because lexical, intra-source and adjacency reads query
`evidence-search-v1`. The actionable performance finding is therefore the per-Event capture
hook/subprocess path, not removal of projection. These LME tasks are label-directed engineering
diagnostics, not deployment traffic or capacity proof.

## 6. 后续轻量采集合同

每个真实任务只需追加一条聚合记录，不保存正文：

```yaml
task_ref_hash:
baseline_tree_sha256:
resolve_calls:
continuation_calls:
working_state_get_calls:
reconciliation_calls:
resolve_latency_ms: []
continuation_latency_ms: []
working_state_get_latency_ms: []
reconciliation_latency_ms: []
context_tokens:
evidence_tokens:
hydration_tokens:
candidates_examined:
evidence_rendered:
event_writes:
state_versions:
task_success: true | false | unknown
useful_evidence_tokens: null
```

达到足够真实样本后再计算 percentile/ratio；当前不设置通过阈值，也不以本文件授权优化机制。
