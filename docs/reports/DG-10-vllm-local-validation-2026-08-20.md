# DG-10 PV-LOCAL Execution Summary

Status: `CANDIDATE.2 EXECUTED / A-B COMPLETE / OPENWORKER MCP LOCAL CANDIDATE`  
Date: `2026-08-20` (Asia/Shanghai)  
Data: `SYNTHETIC / DEIDENTIFIED ONLY`  
External Provider requests/cost: `0 / 0`  
vLLM lifecycle changed: `NO`

## Result

The existing vLLM was called in place. Its container ID, `StartedAt`, restart count `0`, image,
argv, served model and pre/post model binding remained unchanged. No external model API or Provider
credential was used.

| Evidence | Outcome |
| --- | --- |
| Exact target identity | vLLM 0.27.1, `Qwen3.6-35B-A3B-FP8`, 57-file model closure, 2x A100 TP=2 |
| Same-model A/B | 1,000/1,000 validated local inferences; 1,000 unique native IDs; `LOCAL_AB_CAPTURE_COMPLETE_REVIEW_REQUIRED` |
| Quality | baseline 488/500 (97.6%); optimized 500/500 (100%); no safety failures |
| Input tokens | baseline 709,360; optimized 365,560; reduction about 48.5% |
| Model rounds | 500 per variant; optimized added no model round |
| Tool budget | query-only reader-lite schema exactly 250 target-model tokens; frozen gate passed |
| OpenWorker/MCP | S1-S10 local candidate completed; 12 vLLM calls (8 answer routes, 4 tool routes) |
| Worker isolation | no MiLAi token/Runtime DSN; internal agent network; no direct Runtime/vLLM route |
| Cleanup | ephemeral Runtime database, four containers and three networks removed; broker log secret scan PASS |

## Evidence objects

- `DG-10-vllm-local-identity-2026-08-20.json` binds the unchanged target and model/GPU closure.
- `DG-10-vllm-local-ab-2026-08-20.json` is the immutable candidate.1 failed capture.
- `DG-10-vllm-local-ab-candidate.2-2026-08-20.json` is the fresh exact 1,000-call candidate.2
  capture, SHA-256 `976f2043768dd5085df4f0e4a734b692c16805bb9ccfb34e6873e6d5099fc7df`.
- `DG-10-vllm-openworker-mcp-e2e-candidate.2.4-2026-08-20.json` binds the OpenWorker Gateway,
  Worker image, local adapter, broker, S1-S10 normalized results, exact restart state and cleanup.

Preflight and failure-diagnostic calls were local-only and are excluded from the exact 1,000-call
capture. The capture itself was never silently resumed or rewritten.

## Open facts

1. Candidate.2 passes every completed local A/B gate, including the exact 250-token tool ceiling,
   but this is still author evidence and cannot be called independently accepted PV-LOCAL PASS.
2. Candidate.2.1/2.2 fail-closed diagnostics isolated an early root `$schema` timing race.
   Candidate.2.4 compares after identical discovery phases and proves exact raw bytes, full JSON
   semantics, MCP template and wire catalog across restart.
3. The local adapter is necessary because the existing vLLM startup does not enable automatic tool
   choice. The adapter constrains selection to reader-lite recall and the vLLM startup was not changed.
4. This is author evidence. `PVL-05` independent review is absent.
5. Self-hosted inference has no upstream Provider invoice. `OE-F06` remains `OPEN`, so Provider/Beta
   remains `NO-GO` under the original Goal.
