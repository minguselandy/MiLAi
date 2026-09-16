# MiLAi Artifact Archive

This repository is the index and preservation companion for the legacy
MiLAi workspace at `/cra/memory/mx_memory/MiLAi`.

It deliberately does **not** duplicate the multi-gigabyte `var/` tree. The
archive is initially index-backed: catalogs bind authoritative control
artifacts to their immutable legacy paths with sizes and SHA-256 identities.
The original workspace remains the byte store until a separately authorized
offline migration copies those bytes to durable object storage.

## What is stored here

- `catalogs/legacy-artifacts.jsonl`: one record per selected authoritative
  legacy run artifact.
- `catalogs/legacy-artifacts.summary.json`: aggregate counts and catalog
  identity.
- `manifests/source-classification.jsonl`: product/lab/archive/generated/
  external classification of the legacy workspace.
- `manifests/source-classification.summary.json`: source inventory aggregates.
- `manifests/archive-index.json`: SHA-256 closure over the archive catalog
  repository's material files.
- `preserved-user-work/`: exact current and `HEAD` snapshots plus a binary-safe
  Git patch for the two pre-existing user modifications.
- `reports/SPLIT_AUDIT.md`: human-readable split findings and totals.
- `tools/`: deterministic build and validation utilities.

## Trust boundary

This repository is an index, not a claim that every legacy experiment is
valid. `status` records are extracted from legacy artifacts where possible;
they are not re-adjudicated. A SHA-256 match establishes byte identity only.

The legacy workspace is read-only input to these tools. Generation writes
only inside this archive repository. No source, database, run artifact, Git
state, or user file in the legacy tree is modified.

## Rebuild and validate

```bash
python3 tools/build_archive.py \
  --legacy-root /cra/memory/mx_memory/MiLAi \
  --archive-root /cra/memory/mx_memory/MiLAi-Artifact-Archive

python3 tools/validate_archive.py \
  --archive-root /cra/memory/mx_memory/MiLAi-Artifact-Archive \
  --legacy-root /cra/memory/mx_memory/MiLAi \
  --check-legacy
```

Rebuilding intentionally refreshes the snapshot metadata and archive index.
Do not rebuild an already cited catalog in place; create a versioned snapshot
or commit it first.

