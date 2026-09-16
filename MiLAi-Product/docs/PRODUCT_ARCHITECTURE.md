# MiLAi Product Architecture

## 1. Product boundary

MiLAi Product is a local Personal Memory Control Plane, not a benchmark harness and not an
autonomous memory Agent. It separates observation, governed belief, retrieval, and answer context.

```text
Host / Agent
    │
    ├─ OpenWorker UDS relay + broker
    ├─ authenticated Streamable HTTP MCP (Codex; loopback by default)
    ├─ stdio MCP compatibility/debug transport
    └─ typed Python SDK / framework adapter
    │
    ▼
Loopback Flask Runtime
    ├─ Evidence API
    ├─ Proposal / review API
    ├─ Memory query / trace API
    ├─ Host working-state API
    ├─ Context / chat API
    └─ Operations / health API
    │
    ├───────────────┬───────────────────┐
    ▼               ▼                   ▼
PostgreSQL          local CAS blob      optional model/embedding adapter
Canonical Core      store               (never canonical writer)
+ projections
    │
    ▼
one projection/purge worker
```

## 2. Authority planes

### Evidence Plane

Records what a source supplied, with identity, time, scope, permission, retention, content hash,
and revocation state. Evidence does not become truth merely because it was captured or retrieved.

### Canonical State Plane

Maintains `Claim`, immutable `ClaimVersion`, exact-CAS `ClaimHead`, structured `OpenIssue`, grounding,
and version transitions. It is the only long-lived authority-bearing memory state.

### Control Plane

Validates `OperationProposal`, applies commit policy, records `StewardDecision`, and calls the sole
canonical procedure. A submitter cannot approve its own proposal; adapters and models have no
direct canonical DML.

The `codex-full` HTTP facade gives an authenticated Codex Host permission to drive both stages, but
routes them through separate submitter/reviewer Runtime credentials. The canonical actors remain
distinct while MCP audit marks the workflow `SINGLE_HOST_FULL_CONTROL` and
`independent_host_review=false`; this is convenience consolidation, not an independent review claim.

An optional MCP edge registry issues a different Bearer credential for each server-owned Host
principal. First HTTP connection atomically activates that principal and automatically appends
audit. The client sends only the standard Bearer header; no custom identity header or tool argument
can select a principal. The registry stores Token digests only and is not a Memory authority plane.
All users of one process remain in its fixed project; Host identity does not imply tenant isolation.

### Projection and Recollection Plane

Builds Raw FTS, optional dense search, exact canonical views, session/turn adjacency, and derived
projections. All results remain candidates until current permission, scope, revocation, version,
grounding, issue, and authority checks pass.

### Context and Agent Plane

Assembles bounded, traceable context for one request. Context may quote or point to Evidence but
cannot create Evidence or canonical state.

For the P08 reasoning-capable MCP Host, this plane renders `memory-evidence-context-v1`. Codex
decides whether the evidence is sufficient for an ordinary answer, formulates any residual
query, and writes the answer. MiLAi retains memory correctness: scope, revocation, temporal validity,
canonical currentness, Evidence identity, routing and continuation assertions. OpenWorker
`reader-lite` remains a separate compatibility path.

### Host Cognitive Working Plane

Persists Codex-owned, fallible task cognition under authority `HOST_WORKING`. A stable state head
points to immutable versions; exact CAS, TTL, tenant/actor RLS and server-owned project/scope
binding protect updates. Nested Evidence IDs are validated only as exact, currently readable
pointers and are recorded as `HOST_ASSERTED`, never verified grounding.

This plane is neither Canonical State nor Product-11 `RetrievalContinuationState`. Runtime does not
interpret goals, requirements, hypotheses, blockers, decisions or memory needs; recall cannot
mutate it, and it cannot bypass Evidence → Proposal → Review for canonical promotion.

### Memory Activation Layer

Activation policy is a thin Host layer above MCP, not another memory authority plane:

```text
AUTO      Codex chooses exploratory recall and residual continuation
HOST      lifecycle guarantees session-start TASK State access
EXPLICIT  current user intent gates Canonical and destructive workflows
```

`milai codex` is the first HOST path. It derives a Host-owned TASK binding, starts a private
loopback Streamable HTTP MCP, completes `milai_working_state_get(scope=TASK)`, and only then launches
Codex with bounded, non-canonical bootstrap data. The Host decides WHEN; Codex still owns semantic
interpretation. MA-1 adds no Runtime route, table, tool or tool argument.

## 3. Write lifecycle

```text
source observation
→ TX-01 Evidence ingest + Outbox
→ deterministic/model-assisted derivation outside canonical transaction
→ typed OperationProposal
→ validation and CommitPolicy
→ explicit policy/user/Steward decision
→ canonical procedure
→ TX-02/TX-03/TX-04/TX-06
→ ClaimVersion / ClaimHead / OpenIssue / transition + Outbox
```

LLM, embedding, network calls, and external memory engines are prohibited inside the canonical
transaction.

## 4. Read lifecycle

### 4.1 Reasoning-capable MCP Host

```text
user query
→ Host decides whether memory is needed
→ milai_memory_resolve(query, previous_context_id?)
→ existing Runtime acquisition / governance / Context assembly
→ MCP Evidence Context renderer
→ governed Evidence + proven snapshot/continuation metadata
→ Host judges semantic sufficiency
   ├─ sufficient: final answer
   └─ insufficient: focused residual call when useful
```

`retrieval_status` reports retrieval execution only. `continuation: null` means that Runtime made no
continuation assertion; it does not mean the answer or memory universe is complete. Identity,
scope, authority, consistency and budget are trusted Host configuration, never model arguments.
The normal `agent-memory` path has no internal Reader, EvidenceLedger, generated completion decision,
or vLLM dependency.

### 4.2 Runtime and compatibility read path

The stable product direction is a simple, requirement-aware, single-phase read:

```text
query
→ QueryTaskContractV01 planning descriptor
→ QueryExecutionPlanV01 + MemoryQueryIRV02 compatibility projection
→ pre-acquisition tenant/scope/capability envelope
→ canonical exact + Raw FTS + optional dense/session lanes
→ small per-channel quotas and identity deduplication
→ hydration
→ live Evidence/Canonical Gate
→ governed memory availability
    ├─ ordinary/ambiguous language → soft-ranked Reader context
    └─ externally verified structured operands → strict deterministic operator
→ exact Reader-visible trace
```

`QueryTaskContractV01` is an internal planning descriptor for the requested operation, answer shape,
explicit source/time constraints and retrieval hints. It is not proof that arbitrary Raw language
expresses a particular subject, relation, event or numeric operand. The execution plan and existing
`MemoryQueryIRV02` are compatibility projections for the current Runtime path; neither may promote a
lexical match or model interpretation into execution authority.

Ordinary recall and strict operators have different completion needs:

```text
Ordinary lookup:
  governed Evidence available
  → Qwen interprets the natural language
  → Runtime remains non-COMPLETE unless Canonical evidence closes it

Strict operator:
  explicit Canonical mapping / verified projection / typed-tool operands
  + schema/value/unit/time/provenance checks
  + identity/dedup/proof obligations
```

The current natural-language compiler never supplies those structured operands. Canonical
governance alone does not prove that a retrieved value fills a query operand; a future structured
caller or projection must provide the explicit mapping and pass the same Runtime checks.

`BEST_EFFORT_RECALL` is the general fallback for memory questions that the deterministic planner
cannot normalize safely. It still retrieves governed context and may invoke the Reader. Raw prose,
regex interpretation and legacy TypeBinding never grant strict `COMPLETE` or become deterministic
operator operands. Completion and memory availability are separate decisions: an informational read
can be usable while its strict proof remains `PARTIAL` or `UNSATISFIED`.
Progressive acquisition may stop once that governed Reader input is available; this is an
availability stop, not a hidden `COMPLETE` result.

Temporal COUNT and bounded-range queries require deterministic scan/dedup/completeness proof; more
keywords or a model confidence score cannot substitute for range closure.

## 5. Deletion and revocation

```text
authorized revoke request
→ synchronously mark Evidence revoked
→ install GroundingBlock
→ invalidate live Context pointers
→ emit purge/re-ground Outbox
→ asynchronously purge projections and eligible blobs
```

The API distinguishes logical revocation, canonical blocking, derived purge, primary byte erasure,
and backup expiry. A stale projection may retain bytes temporarily, but the live Gate must reject
the candidate immediately.

## 6. Runtime source map

```text
runtime/src/milai/
├── api/              Flask routes, CLI and request boundary
├── domain/           Typed objects and deterministic invariants
├── application/      Use cases, retrieval, context and decision orchestration
├── persistence/      PostgreSQL repositories and transaction boundaries
├── adapters/         Blob/model/embedding and external-I/O adapters
├── workers/          Outbox projection and purge worker
├── observability/    Payload-minimized logs and trace helpers
├── operations/       Init/doctor/start/stop/backup/restore operations
└── config/           Environment settings and fail-fast validation
```

The current code retains historical experimental implementations inside these packages because
eager barrel imports and shared modules make early physical deletion unsafe. Product simplification
will introduce explicit stable interfaces before moving implementation experiments to Lab.

## 7. Integration surfaces

| Package | Role | Authority |
| --- | --- | --- |
| `milai-client` | typed loopback HTTP client | bounded by token/scope |
| `milai-mcp` | authenticated Codex HTTP evidence facade; stdio compatibility tools | no direct Claim DML |
| `milai-openworker-mcp` | host broker/relay and adapter | no model-owned credentials/policy |
| `milai-hooks` | idempotent lifecycle hooks | client-scoped |
| `milai-langgraph` | framework nodes | same client boundary |
| `milai-autogen` | framework memory adapter | same client boundary |

The Runtime never imports integration packages. The Product never imports the Lab.

## 8. Database and migrations

Migrations 0001–0050 are one ordered compatibility history. Migration head is
`0050_host_cognitive_state` (defined by `0050_host_cognitive_state.py`). Some older downgrades are
intentionally unsupported because discarding governance history would be unsafe. The experimental
0050 downgrade is explicitly destructive for Host working state and therefore requires a verified
backup. Never renumber, squash, or rewrite an applied migration.

Runtime identities stay separated:

```text
migration owner
API runtime
Steward executor
projection worker
Audit runner
```

Real-role RLS, direct-DML denial, CAS, idempotency, append-only history, Outbox atomicity, worker
lease recovery, and revocation fail-closed behavior are product-level tests.

## 9. Product versus Lab

Product owns contracts and behavior used by a local deployment. Lab owns datasets, labels,
experiment orchestration, model judging, ablations, paper artifacts, and benchmark-specific
adapters. Lab may call Product through public interfaces or pin a source identity; Product may not
import Lab code.

Frozen architecture reports and independent review artifacts are retained under `docs/reports` and
`docs/reviews` only because the frozen bundle crosswalk refers to them. They are historical
architecture evidence, not active development Goals.
