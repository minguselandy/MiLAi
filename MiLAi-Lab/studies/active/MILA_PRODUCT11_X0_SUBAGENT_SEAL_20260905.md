# Product-11 X0 user-authorized subagent seal

Status: `PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY`

## Result

Two role-specific subagents independently reviewed the 24 opened-development source-only cases.
Neither received the A0 trace, opportunity labels, treatment results, or the peer proposal as an
input. Both proposals passed exact source membership and overlap validation.

```text
annotator                       p11_x0_annotator_c
reviewer                        p11_x0_reviewer_c
cases                           24 / 24 each
normalized instance groups      60 / 60 exact agreement
acceptable turn refs            70
conflict cases                  0
human adjudication              NOT_PERFORMED
model-generated judgment        true
Formal files/cases              false / 0
```

Only after exact agreement did the merger load the frozen label-blind A0 trace. The derived X0
membership was:

```text
continuation opportunity        0 / required >= 8
intra-source opportunity        8 / required >= 8
control/already complete        16 / required >= 8
```

The aggregate X0 gate failed. X1--X4 were not entered, D2 remains Engineering SHADOW, and Formal 500
remains unconsumed. The earlier `0/8/16` proxy diagnosis is corroborated but is not retroactively
relabeled as HUMAN.

## Artifacts

```text
run                             p11-x0-subagent-review-20260905c
orchestration manifest SHA-256  e155bdd70bc6b27580385c0bf645452300c74dad9d6d7dd782fa6e151f2a8778
annotator proposal SHA-256      6cfc7074c4e40a6f2e2f41757596f529643c5046b7ff9c193a479dfa8c0b7dd0
reviewer proposal SHA-256       027ee17ef4fdbbfa3f1e0dedbcf928c8922c0dfbc8a5a802f19b1bc7201fb9ea
merge summary SHA-256           099aa2e626f260ca748ec74f5d70a0596bf1511817c70b0b2366b7a36e129260
sealed labels SHA-256           8f3a790db50b9cb05a184066fa87e160a6fa4ca718ec65937a3d3675fbf583e7
seal receipt                    var/product11/p11-x0-subagent-seal-20260905c/x0-subagent-seal-receipt.json
```

The first `20260905a` receipt remains append-only historical evidence. Architecture review found that
its proposals reused HUMAN-oriented packets and that its seal did not cryptographically require the
merge summary. The `20260905c` run uses dedicated source-only subagent packets, a manifest sealed
before either invocation, empty Evidence IDs, and a seal that recomputes both proposals. Its v0.2
receipt explicitly supersedes the earlier receipt without deleting or rewriting it. Run
`20260905b` contains only an unused pre-execution manifest and made no proposal or claim.

The manifest records the model identity as `codex-subagent-inherited-model` because the orchestration
surface did not expose an exact model build identifier. This limits build-level provenance precision
but does not change the explicit non-HUMAN claim ceiling.

## Verification

The immutable manifest predates both proposals (`12:27:32` versus `12:30:23/26 +08:00`). The final
architecture subagent re-review returned `PASS` with no required fixes. Repository gates after the
correction were:

```text
focused Product-11 tests       24 passed
full Lab pytest                113 passed
boundary check                 PASS
Ruff                           PASS
mypy                           PASS (30 source files)
sdist + wheel build            PASS
wheel contains subagent module PASS
```
