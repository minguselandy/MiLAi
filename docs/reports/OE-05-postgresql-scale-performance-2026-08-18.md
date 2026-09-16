# OE-05 isolated PostgreSQL scale performance

Decision: `PASS` for the stated candidate thresholds  
Boundary: isolated synthetic database, exact `milai_api` role, RLS and live Canonical Gate  
Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Method

`evals/agent_efficiency/postgres_scale.py` created a uniquely named `milai_smoke_scale_*` database,
replayed migrations `base → 0027`, created one formal synthetic Evidence through the API, and bulk
loaded a complete synthetic Claim/Proposal/Decision/Version/Transition/Grounding/search graph at
1, 1k, 10k and 100k sizes. Bulk load uses owner-only `session_replication_role=replica` inside this
throwaway database, so it is performance fixture construction—not canonical workflow correctness
evidence. Every timed result was then read through the exact API role, RLS, repository and Canonical
Gate. The final drop reported `connections_before_drop=0`, owner `milai_owner`, cleanup `PASS`.

Runner SHA-256: `9b94b4a640ae94efa4a5dda02c0e53deaacd3161e35cc7dfc0f0c9ba2527e061`.

Candidate.2 now resolves Alembic paths absolutely and was launched from `/tmp`. Two raw attempts are
retained rather than overwriting an adverse sample:

- contested-host attempt: `OE-05-postgresql-scale-performance-2026-08-18.json`, SHA-256
  `6c45ca45e4ea2a0fb8cab12a254b2b89d87b7ae6f216edf489e82202d1346469`, status `FAIL` while an
  unrelated local vLLM/Qwen workload occupied CPU;
- no-parallel-MiLAi retry: `OE-05-postgresql-scale-performance-candidate.2-retry-2026-08-18.json`,
  SHA-256 `9164974103ad03de0365b13a468a9e8ceefd065e064f2cea834e0d146b578f35`, status `PASS`.

Both attempts measured 100k and cleaned the temporary database with zero connections. The variance
is evidence that these candidate thresholds are device/load-sensitive observations, not an SLO.

## Single-concurrency warm latency

| Claims | L0 p50/p95/p99 | L1 p50/p95/p99 | seed |
| ---: | --- | --- | ---: |
| 1 | 15.903 / 20.888 / 22.883 ms | 22.005 / 30.940 / 31.622 ms | 0.179 s |
| 1,000 | 17.233 / 29.622 / 33.935 ms | 20.849 / 24.197 / 34.364 ms | 0.224 s |
| 10,000 | 16.741 / **20.819** / 23.031 ms | 24.077 / **33.596** / 37.588 ms | 1.008 s |
| 100,000 | 17.898 / **54.611** / 120.494 ms | 43.868 / **61.060** / 74.303 ms | 13.012 s |

Candidate gates at 10k:

- L0 warm p95 `<30 ms`: `20.819 ms`, PASS.
- L1 warm p95 `<100 ms`: `33.596 ms`, PASS.
- 100k workload executed with successful canonical-gated results: PASS.

## Concurrency observation

At 100k, concurrency 4 yielded L0/L1 p95 `60.969/112.798 ms`; concurrency 16 yielded
`285.839/355.963 ms`. Throughput at concurrency 16 was `61.74/48.53 qps`, but per-request tail
latency rose because database and CPU work contend. This is evidence for keeping concurrency bounded;
it is not a production SLO claim. Default embedding inference is separately bounded at 4, while DB
pool and API thread settings remain independent.

## Projection decision

The 100k L1 p95 remains below 100 ms on this device, so the optional canonical-current schema
projection is not justified by current evidence. No new migration or formal-state table was added.
RRF is enabled in application code; MMR is implemented behind an opt-in setting and defaults off
until a quality/latency sweep justifies activation.
