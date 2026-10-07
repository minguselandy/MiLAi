# Conditioned local revisions for grounded agent memory

Working contribution draft, prepared before paired development and confirmation
results. This is not a completed empirical paper or a claim that M is effective.
The results and final method decision must be filled from the preserved actual
experiments before this deliverable is complete.

## Research question and candidate

Can explicit conditional local edits preserve still-valid meaning through repeated
corrections, scoped exceptions and cancellation while correctly applying new
requirements? The proposed comparison separates effects of text locality from
effects of representation. It does not assume that lexical preservation establishes
semantic fidelity, or that a conservative unchanged state fulfills a real correction.

MiLAi-Edit uses the existing MemoryService and SQLite Store. A formed record contains
content and condition units with source-version/range references and modifies or
overrides relationships. M predicts replace, append, override and retract operations;
the program preserves unselected units and relationships. An override changes a
limited scope while retaining the general arrangement outside it. Shared-condition
links are explicit. The implementation supports one override layer and rejects
unsupported nesting. A global correction must explicitly affect every relevant unit;
cancellation removes a selected assertion without affirming its opposite.

These are execution properties, not semantic guarantees. The model can select the
wrong unit, fail to select all affected units, misread a condition, omit initial
formation or cite a source range that does not support its assertion. Ordinary
persisted IDs and immutable revisions establish identity, ownership and actual
effects; they do not certify entailment. No new hash gate, second memory service,
training loop or permanent reviewer is part of the candidate.

## Attribution and evaluation

| Comparison | Question |
| --- | --- |
| B0 plain full rewrite → B1 plain local edit | Does locality improve outcomes using the same plain representation? |
| B0 plain full rewrite → B2 conditioned full rewrite | Does the representation itself account for any gain? |
| B2 conditioned full rewrite → M conditioned local edit | Do the local operators improve outcomes at the same representation? |
| B1 plain local edit ↔ M conditioned local edit | Is explicit conditioning useful beyond ordinary local text edits? |

All arms use identical original observed source characters, chronology, source
allowance, retrieval procedure, generation model and Reader. Writer sees neither
reference memories nor future questions. Primary public evidence uses actual author
HaluMem formation, update and QA scoring; reference-guided update retrieval is a
read-only diagnostic with separate information conditions and denominators.

Native mechanism assessment uses 32 preselected reference items across four users
and twelve source sessions, starting from each arm's actual formed state. NeverWrite
retains that state; RetainAll combines actual old and new revisions without gold
initialization. Initial target absence, unscored judgments and unknown grounding are
reported explicitly. Source review identified enrichment, reaffirmation, cancellation
and uncertainty, as well as assistant-only assertions and a user/reference conflict.
No scoped override or historical erratum was verified in this shortlist. Authored
controlled dialogues cover those gaps in a separate table and do not become official
or natural-user samples.

Native continuous drift reports chronological transition damage events and original
per-session task scores, with invalid gaps preserved. Controlled language/wording
variants form their own banks and remain clustered by source story. Only one
predeclared independent salary/food update pair is swapped; temporal changes are
not generally required to commute.

Sixteen HaluMem users are reserved for untuned-source confirmation after candidate
freeze. The 28-question LongMemEval external comparison is descriptive because all
500 source histories form one overlap component and prior local content was exposed.
Raw RAG, rolling summary, original-author A-MEM adaptation and M share complete
selected histories and bounded Reader delivery. A preselected ten-question audit
checks whole unchanged answers against complete source history. The normal functional
entry then tests one final candidate on old L1-L4 inputs and new post-freeze stories.

## Relationship to prior work

Dynamic notes, source organization, minimal edits, transition-level preservation
assessment, transactional commits, supersession and dependencies are established
ideas. They are not proposed here as new. The [primary-method comparison](MILAI_EDIT_RELATED_WORK.md)
describes actual algorithms and available author implementations rather than treating
paper titles, publication status or code availability as evidence of originality.

The candidate claim is narrower: a measured effect of explicit applicability and
local operators during persistent natural-language maintenance, with a representation
attribution control and downstream tasks. StateMem's unit/dependency/supersession
description is a close representation precedent; HiMem's reconciliation and RARR's
minimal grounded revision are close maintenance precedents. Any final contribution
must explain concrete differences from them and survive B2 and degeneration controls.
If representation or ordinary text locality accounts for the effect, the conclusion
must say so rather than relabel it as a new conditional-edit algorithm.

## Results to be filled from completed runs

| Evidence | Current state | Required final conclusion |
| --- | --- | --- |
| Public wiring | E0 actual predictions and author scoring completed | Wiring validity only |
| Four-arm full development | E1 running, no paired table yet | Paired per-user counts, effects, first failures and uncertainty |
| Native mechanism and controls | Inputs/reviews fixed; actual assessments not admitted | Completion, valid prior damage, cancellation, unsupported additions and QA |
| Untuned HaluMem users | Sixteen reserved; no semantic design exposure | Frozen-candidate source confirmation without tuning |
| External methods and answer fidelity | Paths/subset fixed; actual runs not admitted | Category/all-attempt scores, author adaptation limits and complete-answer errors |
| Drift and sensitivity | Evaluators and authored dialogue fixed; actual runs not admitted | Chronological events, invalid gaps, same-source wording/language/order effects |
| Normal functional integration | Actual SQLite/scripted-provider mechanics checked | Real-model L1-L4 and new stories, partial/UNKNOWN recovery and semantic failures |

No absent result is treated as a zero error rate, improvement or noninferiority.
Development has four natural user clusters; thousands of calls or repeated labels
do not increase that number. LongMemEval has one connected component, while authored
variants are dependent diagnostic stories. All generation and judgments use Qwen3.6
at the user's request, with no independent-family or independent-Judge claim. Root
implements, authors annotations and evaluates; blinding is limited by representation.

## Final decision rule

Prefer the simplest method supported by actual public-task, mechanism and functional
evidence. Report inability to form or apply a requested edit as availability failure,
and assess full answers rather than answer-word matches alone. Preserve all original
proposal errors, optional-review damage/repair transitions, truncated or UNKNOWN
outcomes and unchanged historical r52 results. Completing this research execution
does not promote Product acceptance. The completed reproduction instructions and
final contribution statement must identify the selected candidate and its limits.
