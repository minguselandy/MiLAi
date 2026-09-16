# DG-10 PV-LOCAL vLLM Target Record

Status: `LOCAL TARGET EXECUTED / CANDIDATE.2 A-B COMPLETE / MCP E2E REVIEW REQUIRED`  
Date: `2026-08-20` (Asia/Shanghai)  
Authorization boundary: `call the existing vLLM only; do not modify its startup`  
External Provider API requests: `0`  
External Provider cost: `0`  
Data boundary: `SYNTHETIC / DEIDENTIFIED ONLY`

## User direction

The user selected vLLM, explicitly rejected external model API calls, and required that the existing
vLLM startup remain unchanged. This author record is not an out-of-band independent approval and does
not close `OE-F06`. It authorizes the local candidate work described by ADR-023 only.

## Frozen observed target

| Field | Value |
| --- | --- |
| Provider class | self-hosted vLLM; `PV-LOCAL` |
| Invocation origin | A/B: `http://127.0.0.1:7860`; isolated E2E adapter: `http://172.17.0.1:7860` to the same host-published instance |
| vLLM version | `0.27.1` |
| Container ID | `bcec1ef46198559a99c4c4b0a89fc1fa34382123df121464b5393e491485050f` |
| Container StartedAt | `2026-08-19T03:07:28.539658751Z` |
| Container restart count | `0` |
| Image ID | `sha256:e0cfcfcb9b86e2c2d0d52a93689773f20f380cb8e050a24ce550c44f6f55c5eb` |
| Image repo digest | `sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967` |
| vLLM source revision label | `6e448d0ea9bf3d88d898b65449ca6dc2aec170ac` |
| Served model | `Qwen3.6-35B-A3B-FP8` |
| Model root | `/cra/qwen36-35B` → `/models` (existing read-write bind) |
| Model closure | 57 files; 37,493,018,221 bytes |
| Model closure SHA-256 | `115760819d0006a4d3c05f5722fc89a8b536f63dd5047a73555178e9162ede19` |
| Model config SHA-256 | `570ef7ea45a7e1d3de2b1d3c70c4ac3562d0e768acdc195778cb4f4d95025845` |
| Tokenizer SHA-256 | `5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42` |
| Chat template SHA-256 | `e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259` |
| Quantization | FP8 `e4m3`, dynamic activation scheme, as bound in `config.json` |
| Max model length | 65,536 |
| Reasoning | parser `qwen3`; default `enable_thinking=false` |
| GPU identity | 2× NVIDIA A100-PCIE-40GB, UUIDs bound in identity report, TP=2 |
| NVIDIA driver | `580.178.04` |
| Identity binding SHA-256 | `951564832a9bd75c927b42583a0ee66a688b78aea8a247bd72835cef1db84500` |
| Identity report SHA-256 | `0463fff90754f54c887ed79e54b5db5593b1860cf593c4a89a66c1828eaa3f0e` |
| Workload SHA-256 | `ab5cac3c660835ad1beda1cac56e32b893af476f77b3fb987d4f59d3b8e827e0` |
| Uniform output policy | Same answer-free reason-code definitions and closed JSON schema for both variants; digests retained in capture |
| Planned calls | exactly 1,000 local inferences: 500 baseline + 500 optimized |
| Per-call output ceiling | 160 target-model tokens |
| External egress | prohibited; A/B accepts literal `127.0.0.1:7860`, adapter accepts literal Docker bridge `172.17.0.1:7860` only |
| Provider credential | none |
| Billing | not applicable; no upstream invoice exists |

Exact startup argv is retained in
`docs/reports/DG-10-vllm-local-identity-2026-08-20.json`. The MiLAi evaluation does not issue any
Docker lifecycle or vLLM configuration command.

## Required pre/post conditions

1. Container ID, `StartedAt`, restart count, image, argv, mounts, service version/model and GPU UUIDs
   equal the frozen binding.
2. All 57 model files rehash to the frozen closure before and after the capture.
3. `/tokenize` count equals `chat.completions` prompt usage for every request.
4. Response model is exact, IDs are unique, terminal state is bounded, output is at most 160 tokens.
5. No proxy, redirect, DNS, alternate host/port, external credential or external API is accepted.
6. Reports retain normalized synthetic outputs and hashes only, never raw prompts/memory/model text.
7. Any drift or partial run is `FAIL_PARTIAL`; it cannot be silently resumed or called PASS.

## Existing risks not changed by this work

- vLLM is published by its existing startup on `0.0.0.0:7860` without an API key.
- The model mount is writable.
- GPUs are shared with other observed processes, so latency is not an isolated SLA measurement.
- There is no Provider-native billing export; `OE-F06` remains `OPEN`.

These facts are recorded, not remediated, because the user explicitly prohibited startup changes.

## Executed outcome

- Candidate.2 exact A/B capture: 1,000/1,000 local inferences, 1,000 unique native IDs, pre/post
  identity binding unchanged, external Provider requests/cost `0`; report status
  `LOCAL_AB_CAPTURE_COMPLETE_REVIEW_REQUIRED`. The query-only, Host-policy-bound reader-lite schema
  is exactly 250 target-model tokens and passes the frozen gate.
- Candidate.2 A/B quality: baseline 488/500 (97.6%), optimized 500/500 (100%); optimized input
  tokens 365,560 versus baseline 709,360, with no extra model rounds and no safety failures.
- OpenWorker Gateway + MCP candidate.2.4: S1 through S10 completed with 12 local vLLM calls and
  status `LOCAL_CANDIDATE_REVIEW_REQUIRED`; Worker contained no MiLAi token/Runtime DSN and had no
  direct Runtime or vLLM route. Restart preserved exact raw config bytes, full JSON semantics, MCP
  template and wire catalog when compared after the same discovery phase.
- vLLM container ID, `StartedAt`, restart count `0`, argv and served model remained unchanged.
- `PVL-05` independent review and external-billing `OE-F06` remain open.
