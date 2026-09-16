# UA-07 local-data privacy and threat review

> Decision: `CONDITIONAL PASS FOR SYNTHETIC DATA; REAL DATA NO-GO PENDING USER APPROVAL`  
> Date: 2026-08-17 (Asia/Shanghai)

## Enforced controls

- Blob content uses AES-256-GCM with a random per-Blob DEK, unique content/wrap nonces and AAD
  binding tenant, Blob identity, content hash, media type and length. Wrong key, changed envelope,
  changed ciphertext, symlink and non-regular targets fail closed.
- The KEK is supplied by the local secret environment, never stored in database rows, backup
  manifests, logs, Agent config or model context. Key rotation is atomic, resumable and keeps old
  key material until verification completes.
- The default and currently running mode is `SYNTHETIC_ONLY`. `LOCAL_PERSONAL_DATA` requires
  AES-GCM plus `MILAI_BACKUP_KEY_RECOVERY_CONFIRMED=true`; this repository has not asserted the
  user's authorization.
- API, MCP and framework adapters bind loopback endpoints and scoped bearer profiles. Reader,
  submitter, operator and reviewer capabilities remain separate; no Agent tool can review,
  directly mutate canonical state or bulk-delete a tenant.
- External-memory import starts with a read-only, size-bounded, source-versioned dry run. Reports
  contain content hashes and rejection codes, not source text. Missing tenant mapping, scope,
  observed time, permission or retention sends a record to quarantine. Dry run always reports
  `execution_authorized=false` and performs no database or Blob write.
- Revocation creates canonical blocks before asynchronous physical purge. Backup obligations,
  projections and deletion state are reconciled independently; crypto erase is not treated as a
  substitute for governance.

## Threat decisions

| Threat | Current decision |
| --- | --- |
| Prompt/tool content contains credentials | capture policy and AutoGen/hook adapters reject it; raw prompt/log flags fail closed |
| Agent escalates its own authority | profile catalog is immutable; review and direct canonical tools are absent |
| Stale projection returns revoked authority | exact projection identity plus Canonical Gate; provider outage only degrades recall |
| External export is treated as truth | importer target is immutable Evidence only; Proposal and independent review remain separate |
| Database/backup copied without key | ciphertext remains unreadable; recovery proof is required before private-data mode |
| Host config leaks token | generated configs contain an environment placeholder, not the token value |
| Remote service exfiltrates text | remote access and external embedding are disabled |

## Residual blockers before real personal data

The system cannot authorize real-data processing on the user's behalf. Before changing the data
mode, the user must identify the source and records, approve purpose/scope/retention, confirm key
recovery custody, approve the source mapping report, and witness encrypted backup/restore plus
deletion reconciliation for that environment. An independent integration reviewer must then
accept the evidence. Until those acts occur, MiLAi is eligible only for an Agent Integration Beta
over synthetic/deidentified fixtures—not a Local Private Beta.
