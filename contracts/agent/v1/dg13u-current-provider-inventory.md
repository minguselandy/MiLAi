# DG-13U current provider request inventory v1

Status: `U0 OBSERVED BASELINE / NOT U1 PRODUCT CONTRACT`  
Observed implementation: `integrations/openworker-mcp/src/milai_openworker_mcp/host_adapter.py`  
Data boundary: one local canned-sink request; no real provider, vLLM, or MCP call

This inventory freezes the current executable request behavior before DG-13U U1. It does not accept
ADR-024 or authorize a behavior change. The proposed U1 replacement is
`docs/contracts/DG13U-U1-owner-decisions-v1.md`, decision 8.

## Current ingress and upstream behavior

| Incoming field | Current upstream behavior |
| --- | --- |
| `messages` | Validated as an array, then reduced to the last user text. Existing system, assistant, ordinary tool-call, tool-result, and multi-turn content is not preserved. |
| `model` | Discarded and replaced by `Qwen3.6-35B-A3B-FP8`. |
| `stream=false` | One non-stream upstream request. |
| `stream=true` | Still one non-stream upstream request; the Host emits buffered synthetic SSE afterward. |
| `tools` | Only `milai_recall` is recognized for the legacy visible-memory compatibility round. Ordinary tool definitions are not forwarded. |
| `tool_choice` | Discarded. |
| `temperature` | Replaced by `0`. |
| `top_p` | Discarded. |
| `max_tokens` | Replaced by `96`. |
| `seed` | Replaced by a hash derived from the last user question. |
| `response_format` | Replaced by the F1 answer schema. |
| `user` | Used only as a fallback task identifier; not forwarded as provider semantics. |
| Other top-level fields | Silently ignored rather than typed-rejected. |

The Host constructs a new two-message F1 prompt, adds fixed `chat_template_kwargs`,
`include_reasoning=false`, and a fixed F1 `cache_salt`, and reserves 768 prompt plus 96 completion
tokens. The response is reconstructed from the F1 JSON answer. Native request ID, aggregate usage,
and finish reason are preserved; other provider response extensions are not.

The lower `ProviderExecutionGateway` sends the mapping it receives without another semantic rewrite,
but it cannot restore fields already removed by the Host. Its capability, budget, and transport
failures are not yet mapped to one stable OpenAI-compatible outer terminal.

## Current task metadata producer

There is no real OpenWorker session-lifecycle producer in the current product path. The Host accepts
private top-level fields (`milai_task_state`, `milai_task_relation`, `milai_operation_id`,
`milai_memory_event`, and `milai_required_authority`), while tests/shadow code inject them directly.
The historical runner supplies only a static `--task-session-id`. Missing metadata can create a
generic task, and delayed-operation binding is unit-test-only.

Consequently this baseline cannot claim provider passthrough, ordinary tool preservation, real task
continuity, delayed-result rebinding, or U1 usability.

## Refined real OpenWorker lifecycle observation

The exact-current image
`sha256:e38a10509754560eb3b8e477df4ff0469351ff456d015e7363fb8ffe711bccbd`
contains OpenCode plugin typings and an executable generation path in which `chat.headers` receives
the real `sessionID` and current user-message object immediately before provider serialization. The
baked OpenWorker plugin does not implement that hook and emits none of the candidate MiLAi headers.

Run `dg13u-u0-headers-probe-20260825-003` mounted a temporary user plugin into the exact-current
image and exercised one real OpenWorker/OpenCode session against a local canned sink. The captured
three-header tuple aligned with the native OpenCode session ID and native user-message ID; durable
artifacts contain only SHA-256 values. The call ledger records one canned-sink request and zero real
provider, MCP, or vLLM calls, with no retry. This proves producer feasibility, not U1 product
implementation or owner acceptance.

The same run's redacted request inventory records only structure: top-level keys were `max_tokens`,
`messages`, `model`, `stream`, `stream_options`, `tool_choice`, and `tools`; roles were `system` and
`user`; `stream=true`; `stream_options` contained only `include_usage`; and the current model value
was `AUTO`. No prompt content or credential was persisted. Thus the declared U1 field subset covers
the real current turn shape, while replacing `AUTO` with the exact served model remains an explicit
U1 config/validation change.

## Provider-network correction

The pinned historical gateway image
`sha256:535bb8b7e3b735cc24b04950449f2a70c9905273eafa7d1b322526ecdc5d3860`
cannot carry the candidate tuple. Its `/v1/chat/completions` route parses the incoming body, then
constructs fresh upstream headers containing content type and its own authorization only; arbitrary
`X-MiLAi-*` headers are not forwarded. The exact image and route/service byte hashes are frozen in
`contracts/agent/v1/dg13u-gateway-header-inspection.md`. Therefore unchanged-gateway compatibility
is false.

The local U1 candidate uses the direct provider network already required by the DG-13U goal:
OpenWorker `OPENWORKER_URL` points at the run-owned Host adapter `/v1` endpoint, and the Host alone
owns hidden MCP and vLLM capabilities. Broad gateway header forwarding or body metadata is not an
implicit fallback.
