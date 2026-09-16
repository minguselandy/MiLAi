# DG-25 Requirement-complete acquisition terminal runbook

DG-25 ended at the preregistered S4B post-score gate. The only official S4B
run is `dg25-s4b-joint-score-20260830-001`; it is immutable and must not be
replayed.

The sealed result failed both safety rules:

- minimum AcceptedBindingPrecision: `0.6666666666666666`, required `1.0`;
- WrongComplete across the 16 diagnostic arms: `16`, required `0`.

All schedule, identity, authorization, seal, and boundary checks passed. The
failure therefore stops S5 through S9. It does not authorize Reader/model/
provider/controller calls, formal-holdout access, candidate enablement, schema
changes, product rollout, or adoption of the diagnostic
`final-minimal-policy.json`.

To verify the sealed evidence without reopening scorer-only registries:

```bash
runtime/.venv/bin/python -m pytest -q tests/test_dg25_s10_terminal.py
runtime/.venv/bin/python scripts/build_dg25_s10_terminal.py \
  --run-id dg25-s10-terminal-20260830-001
```

The second command is single-use because the terminal output is immutable. If
it fails, preserve the partial output and append-only failure receipt, repair
only the terminal tooling/evidence binding, and use a fresh S10 run ID. Never
rerun S3A, S4A, or S4B.

Rollback is documentary because no product candidate was enabled. Keep the
candidate OFF, keep the formal holdout untouched, do not publish the scored
diagnostic policy, and route any remediation through a separately frozen
successor goal.
