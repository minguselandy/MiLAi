# MiLAi-Edit common foundation and four-arm prototype

This records P1/P2 engineering delivery, separate from public method-effect
results. The current candidate remains Lab research; historical r52 is unchanged.

## Common-path cleanup

The current functional entry, model admission and memory service use ordinary
persisted source/call/operation/snapshot IDs and immutable revisions. New Sources
use UUIDs persisted against their actual namespace, owner, session, event key and
role. Existing legacy IDs remain opaque strings and can be discovered through
their stored identity metadata. Old run directories are reopened through the
public Store namespace and original message metadata, preserving stored effects.

There are no self-authored source/config/body/tokenizer SHA checks in the current
normal path. Host and embedding capacity still use their actual local tokenizers
and finite input/output limits. Model slots and the continuous ledger are durable
before dispatch. Cooperating ledger writes use the existing exclusive lease and
an ordinary ledger revision. This is not a new claim about uncooperative writers.

New normal checkpoints use a stored ordinary thread reference shared by the Host
and application recovery. Reopening discovers an existing opaque legacy thread
through public checkpoint metadata, without recomputing its old fingerprint. The
ordinary thread index binds run/bank/owner/session/turn identity; an ambiguous old
checkpoint is reported rather than used across owners. Operation keys preserve
the complete caller identity even when an injected UUID factory repeats a value.

The service retains owner/bank isolation, expected-revision compare-and-swap,
transactions, history, no_change, forget, partial/UNKNOWN outcomes and recovery.
Sources remain immutable at their actual capture boundary; references identify
their version and delivered range, without certifying semantic entailment. Same
snapshot IDs cannot be rebound to a changed menu. Same adapter versions cannot
be rebound to changed field mappings.

Document approval/publication uses the actual document ID and immutable integer
version. Editing invalidates approval; only approval of the current version can
publish it. Old database digest columns are retained as legacy storage and are
not public approval proof. Old completed business operations keep their stored
identity on reopen. A later query observing a lost operation's confirmed/partial
effect blocks repeating that mutation, while its original receipt remains UNKNOWN.

The preserved historical runners still contain their old SHA fields. They are
archival replay interfaces, not this execution's normal model path. No historical
score/report/result artifact is replaced. Git and third-party/TLS internals are
outside this common-path cleanup.

The existing offline functional evaluator recognizes the new input schema and uses
the persisted bank/message indices, immutable source revisions and actual response
IDs. Ordinary range/version bindings and recorded output linkage are inspected
without generating fingerprints. Complete Source bindings are distinct from exact
range references. Revoked assistant delivery is checked only in the closed readonly
SQLite snapshot and still requires its recorded capture revision. These provenance
checks do not certify semantic support or business authority. Historical digest
evaluation remains a separate mode for the old sealed queues.

## Method implementation and attribution

All arms use EditMemory over the existing MemoryService and its SqliteStore:

| Arm | Representation | Existing-record maintenance |
| --- | --- | --- |
| B0 | Plain text units | Full record rewrite |
| B1 | Same plain units | replace / insert / delete |
| B2 | Content and condition units; modifies/overrides relations | Full record rewrite |
| M | Same representation and renderer as B2 | replace / append / override / retract |

Unit/relation IDs are ordinary service-generated IDs. An edit_state belongs to
the current record/history revision. There is no separate MemoryService or
permanent reviewer. Untargeted units and relationships remain verbatim in local
edits. M supports one override layer; nested unsupported overrides are rejected.
Explicit shared-condition links control whether a retained condition also applies
to an override. Cancellation does not establish the opposite proposition.

prepare accepts current source refs and exact source_ranges. It delivers only
these new ranges, persisted issued evidence IDs, and the arm's retrieved current
records. Old evidence references include revision/range metadata and are explicitly
body_delivered=false, semantic_support=unchecked. Their old raw bodies are not
silently resent as input. Selecting a source ID cannot widen a delivered range.

The benchmark runner captures complete actual original turns, partitions all
characters with the same 4096-token policy, processes every partition, and saves
source coverage and pre/post state. Writer selects issued evidence IDs and real
record/unit IDs. Proposals and actual receipts remain visible. Known formatting,
length and structural failures consume the first opportunity without an additional
semantic repair; unknown effects remain unresolved. A common Reader receives the
current rendered memories. Reference memories and future QA are evaluator-only.

The optional normal Host integrations are `memory_method=milai_edit_b0_v1`,
`milai_edit_b1_v1`, `milai_edit_b2_v1` and `milai_edit_m_v1`. All use
FunctionalEditMemory over the same service and Reader; its default remains M.
B0/B1 store `plain_v1`; B2/M store the same `conditioned_v1`. B1 accepts
replace/insert/delete, and M accepts replace/append/override/retract.
B0/B2 regenerate every unit and relation through the original whole-state
constructor, retaining the record ID and metadata scope. No arm silently converts
an existing incompatible representation or legacy record. Tools retain their
normal names; formation takes source-grounded units/relations. M/B1 revisions take
the current read handle plus local edits; B0/B2 revisions take the current read
handle plus the complete replacement units/relations. For B0/B2, omitted/null
units confirms exact no_change; explicit empty units withdraws the whole record
and requires actually delivered cancellation evidence beyond its old affirmative
support ranges. Extra tool arguments, including local `edits`, are rejected rather
than silently discarded as a no-change request. Whole withdrawal retains readable
history and is distinct from forgetting. Adapter availability does not select a
scientific candidate. Successfully delivered raw reads register
their actual fragment handles. Business observations register only after the
corresponding ToolMessage survives visibility and response filtering. A captured
but undelivered source is not write evidence. Original UNKNOWN mutations remain
UNKNOWN; a later actual public discovery can support memory-only completion while
the application wrapper prevents repeating a confirmed business effect. Review
hooks, when selected, use immutable persisted proposals and selected actual ranges;
reopening or replay does not silently re-run a review or commit an unsupported edit.

## Verification and limits

Actual SqliteStore checks cover initial formation for four arms, same-ID revision
and reopening, plain insertion/deletion, condition append, scoped override,
unchanged outside scope, shared-condition updates, cancellation, stale revision,
atomic multi-target rejection, durable no_change, exact range delivery, history,
forget and recovery after a real committed write loses its response. Root's extra
checks cover old business-ID migration, cross-turn discovery without repeated
business effects and reopening an existing legacy bank.

The source owner's expanded engineering set has 272 passes; root's final normal
functional/queue/capacity/HTTP set has 273 passes; the four-arm wiring/recovery/
admission startup set has 66 passes; the document lifecycle set has 13 passes.
Sets overlap and are not summed. Strict typing of the actual modified modules,
both dependency boundaries and the declared source/CI ownership matrix passed.
The wider historical compatibility audit continues separately and is reported
in the progress file; an old fingerprint assertion is not new method evidence.

The wider current-memory audit is now 594 passed, 8 optional-environment skips and
31 local-asset deselections, with 67 separate historical correction checks on their
original source. Normal Host M/B1 save/partial/UNKNOWN and same-ID replacement
integration passes ten focused checks; checkpoint reuse passes five. The source
owner's expanded M/B1 adapter set passes 21; the earlier review/boundary set passes
87. The complete normal Host plus M/B1 adapter regression passes 255 checks
(`/tmp/milai-edit-host-adapter-regression-4.log`). Evaluator/external/wiring/denominator
preparation passes 29 checks, with ten
evaluator checks. Global strict typing passes 210 source files and source/CI
registration owns 242 active files. These overlapping counts describe
mechanics and compatibility, not additional independent model samples.
The normal-schema offline evaluator's historical/SQLite/actual Host-linkage set
passes 76 checks and strict typing. Scripted provider replies in those checks do
not constitute actual-model functional acceptance.

The 2026-10-05 four-arm normal-entry extension passes 46 actual SDK adapter checks
and 252 complete normal Host checks. The 26 focused Host checks are part of that
252-case set, not additional samples. New checks cover complete B0/B2 rewrites,
B2 conditions/relations, pure confirmation, same-ID history/CAS, explicit rejection
of local-edit arguments, actual partial/UNKNOWN business evidence, recovery across
both Store put windows and Reader/forget after reopening. The source owner's first
expanded test run exposed a missing test import; it was corrected and the complete
46-case set rerun. Strict typing of both changed modules, Ruff, package/tools
boundaries and the 242-source ownership matrix pass. All nine frozen E1 source
copies and the original plan remain unchanged. Four-arm public-input preflight
passes 540 repeated checks of 135 historical cases, with zero HTTP or semantic
initialization. Source/effect compatibility remains separate from E5 model acceptance.

These are engineering checks. They do not establish correct semantic scope
selection, useful public-task outcomes, independent Judge validation, cross-family
generalization or Product acceptance. E1 is running with a fixed implementation
and retains early ordinary model errors; later stages remain required.
