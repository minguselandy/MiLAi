# UA-06 Retrieval Quality 与目标设备证据

> Decision: `PASS FOR OPTIONAL LOCAL ONNX PROVIDER`  
> This is a measured candidate baseline, not a product SLA.

## Quality and identity

The provider protocol has explicit provider/model/dimension/normalization/code identity. Migration
`0027_embedding_identity` binds every vector row and lookup to the exact identity; scores from
different spaces cannot mix. Loading is explicit and local—no import-time network call.

Fixture SHA-256 `0c5b4fd424769574f97a078043fdcc7aae82ea82056ea3596cb50d151d5bef2c`
contains 13 synthetic cases. Deterministic hash top-1 is `0.5384615`; local
`all-MiniLM-L6-v2` ONNX top-1 is `0.8461538`; absolute gain `0.3076923` exceeds the frozen `0.10`
gate.

## Target device measurement

Evidence file: `evals/embedding/all-MiniLM-L6-v2-target-device-result.json`.

```text
device                 x86_64 Linux, 32 CPU, CPU_ONLY, Python 3.11.13
concurrency            1; cold first call then warm
ONNX cold              1050.172 ms
ONNX warm p50/p95/p99  14.529 / 15.069 / 15.548 ms
throughput             28.967 calls/s
failure rate           0
external cost          USD 0
```

The workload is provider-only, so database rows/index bytes/projection lag are explicitly `0/0/N/A`
rather than invented. A forced provider outage test proves vector degrades, FTS/canonical fallback
continues and a no-candidate request safely abstains; no authority hard gate is bypassed. Provider
privacy and opt-in rules are in `docs/security/embedding-provider-privacy.md`.
