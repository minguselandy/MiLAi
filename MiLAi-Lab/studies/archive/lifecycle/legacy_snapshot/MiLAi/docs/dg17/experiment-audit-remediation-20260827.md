# DG-17 experiment-audit remediation

Status: `PARTIAL_LOCAL_REMEDIATION_COMPLETE_EXTERNAL_BLOCKERS_REMAIN`

The provisional same-family audit remains `FAIL`; it was not rewritten. This
receipt records only deterministic remediation completed after that audit.

## Completed without external calls

- Q0 future oracle C/D contexts now use actual MemoryQueryCompiler v0.2 output.
  Unexecuted operator accuracy is `null` with denominator zero, and diagnostic
  success uses strict EM.
- Q3C no longer sends deterministic route/operator targets to the hint provider.
  Authored multilingual fixtures are explicitly opened-development diagnostics,
  not held-out or unseen evidence.
- Q6 atom coverage is source-turn + normalized-span aware and separately reports
  atom, unique-span, and source-turn denominators.
- Terminal sufficiency `COMPLETE` with missing required Evidence is counted as
  wrong COMPLETE, including when no derived result exists.
- DG17 Q6 uses a label-fixed ideal nDCG denominator; the frozen generic DG12 paper
  scorer was not modified.
- Cross-case contamination and label-leakage counters are measured from real
  source/key traces instead of asserted as zero.
- Semantic hint output is represented only as a counterfactual cost overlay unless
  an actually executed product arm exists.
- Q6 preflight binds the local gate, v0.1 compatibility disposition, and honest
  annotation manifest. It remains `execution_authorized=false`.
- The local gate now includes Reader/Exact-Match stability and passes 332 tests.
- An end-to-end source-identity test exposed and fixed the live-scorer
  `source_ref` / `source_turn_ref` mismatch.

## Preserved historical evidence

Historical Q0/Q1/Q3C/Q4/Q5 receipts and the original FAIL audit were not edited or
superseded. Their claim ceilings remain those recorded by the audit.

## Remaining blockers

- The manual atom/slot/join/IR labels still need a recorded independent review and
  adjudication.
- The generic paper nDCG fix belongs to DG12 frozen-harness change control.
- Corrected Q0 multi-seed, unbiased Q3C, Q6 matched, governance/cost/operability,
  Q7, and final release review require resumed external execution.

## Receipts

- Local gate:
  `var/dg17/local-gate/dg17-local-gate-20260827-010/receipt.json`
  (SHA-256 `ce38382d1fca9c26c4ccbfd5cf8172532e1f21a70ad9a7f2938a30af01c4b26a`)
- Q6 preflight:
  `var/dg17/q6/dg17-q6-preflight-20260827-007/preflight.json`
  (SHA-256 `fa4e59fbc9d4fc91e1623cd7e704a0f96612718fc50b3a6913c5b4088a07675b`)

External model/database/retrieval/Reader calls during remediation: `0`.
Release remains `NO-GO`.
