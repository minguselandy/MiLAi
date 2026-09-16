# OE-00 Agent efficiency baseline and optimized regression

Status: `PASS` for deterministic offline regression; `NOT PROVIDER BILLING EVIDENCE`  
Runtime boundary: Schema `0.1.x EXPERIMENTAL`, Implementation `CANDIDATE`, Schema freeze `NO-GO`

## Reproducibility boundary

- Fixture: `evals/agent_efficiency/fixtures.json`
- Fixture SHA-256: `a208db677f76f7af38e664e772f537d84dbea47d956becc0faa85e76a06939fc`
- Runner SHA-256: `422a87346bb48271f80733b6be2451874933c9f50d7e777439c952213d27381b`
- Raw report SHA-256: `472b1f78c4f1ff0f46e64a12bed4e42315c26bc579d933de580d37dd724f10f4`
- Evaluation tokenizer: `ospc.regex.v1`; provider exact: `false`
- Evaluation model: `offline-synthetic/no-llm-called`
- Provider price snapshot: all price fields `null`, because no provider request was made
- Device: Linux 5.15 x86_64, Python 3.11.13, 32 logical CPUs
- Workloads: exact 20/100/500 turns, every fifth turn labelled as requiring memory
- Baseline: static reader-detail schema plus recall/context on every turn
- Optimized: deterministic NONE/L1 router, reader-lite only on recall turns, Context Compiler v2

The baseline and optimized path use the same turns, result payload, tokenizer, and route labels. This
is a capacity/regression comparison, not a historical provider invoice.

## Token result

| Turns | Required recalls | Baseline MiLAi input | Optimized MiLAi input | Reduction | Route accuracy |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | 4 | 14,160 | 2,056 | 85.480% | 100% |
| 100 | 20 | 70,800 | 10,280 | 85.480% | 100% |
| 500 | 100 | 354,000 | 51,400 | 85.480% | 100% |

The 100-turn optimized total is below the `<30,000` design gate. It consists of 7,780 memory
tokens and 2,500 reader-lite schema tokens. The runner records `provider_usage_verified=false` and
does not project these values into money.

## Local router/compiler latency

Cold first operation: `0.884 ms`.

| Concurrency | samples | p50 | p95 | p99 | throughput |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 160 | 0.016 ms | 0.834 ms | 0.925 ms | 4,908.28 ops/s |
| 4 | 160 | 0.016 ms | 0.898 ms | 6.905 ms | 4,738.92 ops/s |
| 16 | 160 | 0.018 ms | 0.867 ms | 1.165 ms | 4,165.96 ops/s |

This timing excludes HTTP, PostgreSQL, embedding and model inference. Those are measured separately.

The retained report now distinguishes logical recall operations from executed I/O. For 100 turns,
the baseline has 100 logical recalls and the optimized path has 20; this offline runner executes zero
network/service round trips and zero provider model calls. Consequently `extra_model_round_trips` and
end-to-end Agent wall time remain null rather than being fabricated. Local router/compiler workload
wall time was 28.989 ms.

## Dataset generator manifests

| Claims | Canonical JSONL bytes | SHA-256 |
| ---: | ---: | --- |
| 1 | 363 | `95bdc089c483c1f0e1e85ebbc6ddb80415dbb70cf5feaf6a408677377a2991d6` |
| 1,000 | 364,893 | `1b91041dcf41eaa9d356a0418112500e1346e42a2133dad51f52b746e09b3f73` |
| 10,000 | 3,658,894 | `3847a3c7c6d7a08e2c9249c4b6c94a089b66d3682a582d7d49f398e7c245bb11` |
| 100,000 | 36,688,895 | `ea3ab3c721c0a53cb0ff85ae7d42b4cd1624a9e074343c97b6c35998dcff9732` |

The corpus is streamed for hashing and is not retained in the repository.

## Framework mapping

- Generic direct: router + compiler + per-turn dynamic tool catalog.
- Hook: cross-process `MemorySlot` checkpoint; no model-visible recall tool.
- MCP: default reader-lite instead of static reader-detail.
- LangGraph: one replaceable prompt slot and reference-only checkpoint.
- AutoGen: one replaceable data message; the 500-identical-turn test performs one recall after a
  canonical/issue validation cache hit, rather than 500 recalls.

## Honest limits

Provider input/cached-input/output counters and real billing remain unverified until a host supplies
its exact tokenizer and provider-returned usage. The SDK now supports that path and refuses to label
locally inferred counters as verified.
