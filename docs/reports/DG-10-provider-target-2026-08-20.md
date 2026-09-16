# DG-10 Provider Target Record — awaiting explicit authorization

Status: `PVG-00 NOT STARTED / AWAITING USER APPROVAL`  
Date: `2026-08-20` (Asia/Shanghai)  
Requests made: `0`  
Cost incurred: `0`  
Data boundary: `SYNTHETIC / DEIDENTIFIED ONLY`  
Repository secret status: `NO PROVIDER CREDENTIAL RECORDED`

This record is intentionally incomplete. The DG-10 goal explicitly states that the repository and
goal document do not authorize external Provider access, account use, recharge, or spend. No model or
Provider is selected by default. An operator/user must fill and explicitly approve every field below
out of band before `PVG-00` can advance.

## Required frozen target

| Field | Required approved value | Current value |
| --- | --- | --- |
| Provider legal name | exact contracting entity | `UNAPPROVED` |
| API origin | exact HTTPS origin | `UNAPPROVED` |
| Exact model identity | immutable model ID/version/snapshot, not a floating alias | `UNAPPROVED` |
| Tokenizer | exact ID/version and count implementation | `UNAPPROVED` |
| Chat/tool serialization | exact version/canonicalization | `UNAPPROVED` |
| Region | exact processing region | `UNAPPROVED` |
| Retention/data mode | exact no-training/retention settings and evidence | `UNAPPROVED` |
| Pricing | source digest, currency, effective time, input/cached/output/tool rates | `UNAPPROVED` |
| Request ceiling | exactly 1,000 native calls | `UNAPPROVED` |
| Per-request input ceiling | target-tokenizer count | `UNAPPROVED` |
| Per-request output ceiling | Provider-native maximum | `UNAPPROVED` |
| Total approved cost | exact currency amount; `$20` is not pre-approved | `UNAPPROVED` |
| Reconciliation tolerance | exact value, never above 1% | `UNAPPROVED` |
| Egress IP allowlist | approved static Provider IPs TCP/443 | `UNAPPROVED` |
| Credential aliases | `MILAI_PROVIDER_CREDENTIAL_*` aliases only | `UNAPPROVED` |
| Execution Host | exact machine/OS/kernel/runtime/namespaces/Landlock/helper identity | `UNAPPROVED` |
| Execution window | start/end timestamps and timezone | `UNAPPROVED` |
| Evidence custody | repository-external location category and custodian | `UNAPPROVED` |
| Independent reviewer | identity and independence statement | `UNAPPROVED` |
| Data set | frozen synthetic/de-identified workload SHA-256 | `UNAPPROVED` |
| Approval | approver identity/time and out-of-band approval SHA-256 | `MISSING` |

## Provider capability evidence required before selection

The chosen Provider must support all of the following for the exact model:

- a unique native request ID for every call;
- Provider-native input, cached-input, and output token usage;
- exact terminal state and finish reason;
- a receipt lookup or equivalent native evidence whose digest can be bound;
- an upstream billing export/invoice with per-request IDs and costs;
- pricing effective-time evidence and deterministic cost recomputation;
- fixed or independently attestable model identity and tokenizer/serialization;
- the approved retention, training, region, and data controls.

A Provider without exact request-ID billing coverage cannot be used to close `OE-F06`. A local vLLM
lane cannot replace the upstream billing requirement.

## Approval statement to execute out of band

The approver must explicitly state all filled values and a maximum cost in one immutable approval
object, then supply its SHA-256 without placing credentials or account data in this repository. The
minimum semantic statement is:

```text
I approve exactly 1,000 charge-bearing requests to <Provider legal name>,
API origin <origin>, exact model <identity>, during <window>, from Host <identity>,
using only workload <SHA-256> classified SYNTHETIC/DEIDENTIFIED, with per-request
input/output ceilings <values>, static egress <IPs>, reconciliation tolerance <value <=1%>,
and an absolute total cost ceiling of <amount currency>. Evidence custodian is <identity/category>;
independent reviewer is <identity>. No real personal data is authorized.
```

Until that approval exists, the only permitted work is local package/adapter implementation,
synthetic tests, evidence planning, and read-only Provider capability research. `OE-F06`, `PVG-00..04`,
`AIG-00..01`, and Provider/Beta remain `NO-GO`.
