# Product-11 X0 Subagent-Sealed Execution Audit

Date: `2026-09-05`  
Status: `PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY`
Revision: `v0.2 VERIFIED ARTIFACT CHAIN`

## Authorization and claim boundary

The user explicitly authorized continuation of the experiment with subagents instead of human
review. This creates a parallel `SUBAGENT_SEALED` opened-development branch. It does not edit the
historical HUMAN workflow, set `human_adjudication_status=COMPLETE`, or establish human gold.

```text
claim ceiling                 OPENED_DEVELOPMENT_MODEL_ADJUDICATED
human adjudication            NOT_PERFORMED
Formal access/scoring         false / 0
Product label access          0
Product behavior changed      no
```

## Independent review and merge

Two role-specific subagents received separate source-only packets and were instructed not to inspect
the peer proposal, A0 output or treatment results. The merger bound the role, orchestrator-assigned
identity, input packet digest, invocation identity and output digest. This establishes explicit
execution provenance, not statistical independence between model judgments.

```text
annotator                     p11_x0_annotator_c
reviewer                      p11_x0_reviewer_c
cases                         24 / 24 each
normalized groups             60 / 60 exact agreement
acceptable exact turn refs    70
conflict cases                0
```

The execution used dedicated `SUBAGENT_*` source packets and an immutable orchestration manifest
created before either invocation. Packet validation rejects A0/treatment/proposal fields, wrong role,
fixture drift and case-order drift. Because no Evidence-ID mapping is present, non-empty
`acceptable_evidence_ids` are rejected. The merger ignored local group IDs and notes. It compared
exact turn membership, required semantics and source/session provenance derived from the frozen
source fixture. The conflict path is fail-closed and emits only semantic hashes, never adjudicated
rows. The seal reloads and recomputes both proposals, so adjudicated rows and merge metadata cannot
be supplied as self-attesting inputs.

## X0 result

Opportunity assignments were derived only after exact agreement by joining the labels with frozen,
label-blind A0 trace `eef498d36c35b102ca6943469c7b203113237b1bf63c3cb17cd8c95f9dd27a95`.

```text
continuation opportunities       0 / required >= 8
intra-source opportunities       8 / required >= 8
control/already-complete         16 / required >= 8
capability minimum               6 / required >= 3
overlapping exact turn refs      0
opportunity gate                 FAIL
```

The verified-chain sealed label SHA-256 is
`8f3a790db50b9cb05a184066fa87e160a6fa4ca718ec65937a3d3675fbf583e7`. The authoritative receipt is
Lab `var/product11/p11-x0-subagent-seal-20260905c/x0-subagent-seal-receipt.json`; its merge-summary
SHA-256 is `099aa2e626f260ca748ec74f5d70a0596bf1511817c70b0b2366b7a36e129260`.

The prior `20260905a` receipt remains historical and is explicitly superseded, not overwritten.
Architecture review found that it reused HUMAN-oriented packets and allowed a merge-summary bypass.
The corrected run repeats both independent reviews with new subagents and records an append-only v0.2
receipt. The unused `20260905b` pre-execution manifest produced no proposal or result.

## Disposition

The frozen slice cannot test P11-C1 because it contains no continuation opportunity. Under the
preregistered X0 gate, X1 and X2 treatment are not entered independently of the fact that eight
intra-source opportunities exist. X3/X4 are consequently not eligible. The slice must not be reshaped,
A0 retuned, or Formal 500 consumed to fill the denominator.

D1 persisted-frontier and D2 lexical intra-source SHADOW remain valid Engineering baselines. This
audit does not upgrade either to a quantitative P11-C1/P11-C2 effect claim. Schema remains
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
