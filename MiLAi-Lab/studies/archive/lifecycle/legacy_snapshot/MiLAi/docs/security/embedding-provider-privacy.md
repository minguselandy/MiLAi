# Embedding provider privacy boundary

> Status: `ENFORCED FOR LOCAL AGENT INTEGRATION BETA`  
> Scope: MiLAi Runtime `0.1.x CANDIDATE`; Schema remains `EXPERIMENTAL`.

MiLAi's enabled real embedding provider is the local CPU-only ONNX copy of
`sentence-transformers/all-MiniLM-L6-v2`. Model and tokenizer files must already exist under the
configured local model directory. The provider performs no download, telemetry, remote inference,
DNS request, or API call. A missing model, tokenizer, runtime, or failed inference raises
`EmbeddingUnavailable`; retrieval records `vector` as degraded and continues through L0/FTS or
canonical fallback. Evidence ingest, review, revoke, and the Canonical Gate do not depend on the
provider.

The embedding input is a query or canonical projection text already authorized for the current
tenant. Vector rows remain tenant-scoped derived state. Provider identity binds provider, model ID,
source dimensions, projection dimensions, normalization, and code version; retrieval only selects
the exact identity, so model upgrades cannot mix score spaces. Rebuild deletes only derived state
and replays Outbox data—it never rewrites Evidence, Claim, OpenIssue, or review history.

External embedding APIs are disabled. Enabling one requires a separate privacy review and explicit
user opt-in covering data classes, destination, retention, deletion, incident handling, and cost.
No such gate has been approved.
