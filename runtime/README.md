# MiLAi Runtime

> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

This directory contains the MiLAi Lean V1 candidate runtime. It is a modular Flask application,
one background worker, PostgreSQL/pgvector, and a local content-addressed blob root. It does
not import or require ReMe, hindsight, graphiti, Mem0, MemoryIntention, or OSPC.

Logical Architecture 1.0.0 is frozen and independently verified. The Runtime remains experimental:
Agent Integration v0.1 candidate.2 is awaiting independent re-review, Schema 0.1.x is not frozen,
and real personal data is still denied until an encrypted backup/key-recovery drill is independently accepted. The
current migration head is `0032_reviewer_actor_separation`; migration `0027_embedding_identity` binds vector rows
and queries to one projection identity so different model spaces cannot be mixed. See
`../docs/runbooks/local-runtime.md` and `../docs/runbooks/agent-integration.md`.

Runtime commands are defined by this `pyproject.toml` and its lock file:

```bash
uv sync --frozen --dev --extra embedding
uv run milai-ops init
uv run milai-ops doctor --json
uv run milai-ops start --background
uv run milai-ops status --json
uv run milai-ops smoke-test
uv run milai-ops stop
uv run milai-ops rotate-local-credentials --help
uv run milai-ops --help
uv run pytest -m "not integration"
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run mypy
```

The candidate vertical slice includes Evidence ingest/revoke, DeriveAndDiagnose, governed
Proposal/Steward review, versioned Claim/OpenIssue state, L0/L1 retrieval through a persisted
QueryPlan and Canonical Gate, protected ContextCapsules, traceable Chat, and Episode/Settlement.
Action-sensitive Chat requires a fresh `USER_CONFIRMATION` Evidence reference; a confirmation
string alone is intentionally rejected.

Stable candidate routes include:

```text
POST /v1/memory/query
GET  /v1/capabilities
GET  /v1/proposals?status=PENDING_REVIEW&limit=50
GET  /v1/retrieval-traces/{id}
GET  /v1/system/watermarks
GET  /v1/system/degraded-routes
GET  /v1/deletion-requests/{id}
```

Agent packages are isolated under `../integrations/`: `milai-client`, `milai-mcp`,
`milai-langgraph`, `milai-autogen`, and `milai-hooks`. Runtime never imports them. MCP is local stdio
only and exposes exact reader/submitter/reviewer/operator allowlists. The reviewer uses a separate
actor and the minimal `memory:read` + `proposal:review` capability set; no profile can write a Claim
directly, and the submitter cannot approve its own Proposal.

The query-first resolver remains task-free. Configurable detail-profile clients may add an optional
TaskContext containing only project/entity/type narrowing hints and a trace-only action-risk hint;
Runtime intersects it with deployment-bound constraints before the existing planner and Canonical
Gate. TaskContext cannot grant scope, authority, consistency, write, or review capability.

Evidence ingest carries `data_classification=SYNTHETIC|DEIDENTIFIED|PERSONAL`; the Runtime checks
it against the active data mode before Blob write. The classification is a trusted host/user
assertion, not automatic PII detection.

Database migrations require `MILAI_MIGRATION_DATABASE_URL` and run with the migration owner.
The API and worker must use their separate login roles.
The projection worker uses `MILAI_EMBEDDING_BATCH_SIZE` (default `32`) for local provider
`embed_many` calls; logical items, actual inference batches, exact-dedup hits, and stage durations
are reported as payload-free metrics.
The server-only `MILAI_CAUSAL_TOKEN_SECRET` must be at least 32 characters and distinct from
the client-facing `MILAI_API_TOKEN`; it authenticates tenant-bound read-your-writes positions.
Consistency backup/restore additionally requires PostgreSQL 16 client tools and the dedicated
Audit Runner URL. Operational commands and destructive confirmations are documented in
`../docs/runbooks/first-run.md`, `../docs/runbooks/credential-rotation.md`,
`../docs/runbooks/backup-restore.md` and
`../docs/runbooks/projection-and-purge-recovery.md`.
