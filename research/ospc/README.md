# OSPC falsification pilot

This directory is a deterministic offline research harness for DG-R01. It is not a product package, product dependency or production compressor.

```text
RQ pending / novelty unvalidated
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```

The harness compares a full-raw reference, naive recursive retention, extractive top-K, hierarchical
summary, structured eviction, a strong typed-state baseline, a static always-protect-OpenIssue absorber,
the OSPC candidate, four ablations and an equal-budget oracle. One frozen regex tokenizer charges
structured keys, payload punctuation, common method metadata and recovered tokens. No method uses an
LLM or receives extra retrieval access.

`B_min` is the exact cost of Goal, hard constraints, issue identity, target, both Evidence branch sets,
Evidence pointers, discharge rule, dependencies, authority and the common output envelope. A budget
below that minimum returns `INFEASIBLE_UNDER_BUDGET` for every method; such rows are not silently counted
as zero false closure. The result records charged-token, wall, process-CPU, GPU, recovery, fallback and
model-call costs plus complete failure distributions.

## Isolation contract

- Code uses only the Python standard library and imports no `runtime/src/milai` module.
- It reads only checked-in synthetic JSONL and writes only `research/ospc/results`.
- It has no network, database, environment-secret, blob-store or canonical write path.
- External memory projects are read-only prior-art snapshots; none is imported or executed.
- A research result cannot modify product policy. Product integration would require a separate ADR and product gates.

## Reproduce

From the `MiLAi/` root:

```bash
runtime/.venv/bin/python -m research.ospc.generate_fixtures
runtime/.venv/bin/python -m research.ospc.run_benchmark
runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v
```

The generator is deterministic. Compare `fixtures/manifest.json` and the fixture hash embedded in `results/pilot_metrics.json` after reruns.
