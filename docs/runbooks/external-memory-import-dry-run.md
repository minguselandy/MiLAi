# External memory import dry run

The dry run never connects to PostgreSQL, writes a Blob, creates Evidence/Proposal, or authorizes a
later import. Run it only against an explicit export copy:

```bash
cd /cra/memory/mx_memory/MiLAi/runtime
.venv/bin/milai-ops import-dry-run \
  --env-file .env \
  --source mem0-json-v1 \
  --input /explicit/read-only/export.json \
  --report /explicit/private/report.json
```

Supported versioned shapes are `mem0-json-v1`, `graphiti-json-v1` and `hindsight-json-v1`. Every
record needs an external ID, content, observed time, source scope, tenant mapping, an explicit
`permission_snapshot.authorized=true`, and readable/legal-hold retention. Ordinary exports often
lack permission or tenant evidence; quarantine is expected and must not be bypassed by inventing
values.

The report is created with mode `0600` and never overwritten. It contains content digests, sizes,
normalized lineage metadata and rejection codes, never source content. A later import requires a
separate source mapping review, privacy approval, user authorization, encrypted recovery/deletion
drill and immutable Evidence import implementation. There is intentionally no “force import” flag.
