# DG-13U U1 user-direct execution override

Status: `EFFECTIVE / USER-DIRECT EXECUTION / MODEL AUDIT REQUIRED`  
Effective at: `2026-08-25T14:51:19Z`  
Goal: `DG13-U1 = LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE`

## User directives

The active user issued these exact instructions in this execution thread:

1. `继续，不需要authority，直接执行`
   - UTF-8 SHA-256: `a123b83ac576021682181118044b327db3e0e11a0c24f8324f213294d9c66ca3`
2. `完成goal文档的全部任务，不需要人类批准，使用模型审计替代`
   - UTF-8 SHA-256: `61f8088c4646185407ed9351facb3ea51eb1a37777f9585810cf262bad3dd9af`

## Bound decision set

| Artifact | SHA-256 |
| --- | --- |
| `docs/contracts/DG13U-U1-owner-decisions-v1.md` | `9e38110f2eaea14f4fe94465b24e994b7ab7d770a2a0bfce5349a6d358f6745d` |
| `contracts/agent/v1/openworker-task-metadata-headers.md` | `b36feaff924cc10275040a458f17449907621b4ecadf5af2f92771784db60c4f` |
| `contracts/agent/v1/dg13u-u1-candidate-fixture.json` | `47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555` |

Decision: `ACCEPT_FOR_EXECUTION_BY_USER_DIRECTIVE`

The nine bounded decisions in the proposal are accepted as the executable U1 contract. Human owner
identity and a separate human acceptance receipt are not required by the active user directive and
are therefore not fabricated. All approval/review checkpoints in the DG-13U goal are replaced by
independent, read-only model audit evidence. A model audit cannot silently change the accepted
contract; `REVISE` findings require an isolated failing test, a minimal repair, a negative twin, and
the owning gate before re-audit.

## Scope and non-expansion

This override authorizes the behavior-changing work needed to complete every task in the DG-13U goal
document. It does not edit or supersede `architecture/v1.0/`, does not authorize U2/U3/U4, Direct or
HTTP memory transports, portable leases, push invalidation, formal DG-12 labels/holdout access, or a
Production/Beta claim. The product Provider remains the existing local vLLM, whose lifecycle and
configuration must not be changed.

Completion still requires real exact-current OpenWorker-to-vLLM evidence, U1-G0 through U1-G5 PASS,
cleanup/reconciliation closure, and an independent `gpt-5.6-sol`/`xhigh` read-only model audit with
no open P0/P1 finding.
