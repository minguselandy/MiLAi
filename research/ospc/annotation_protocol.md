# OSPC pilot annotation protocol

> Protocol: `ospc.annotation.v1`  
> Data class: synthetic, immutable after manifest hashing  
> Product access: none

## Unit and episode boundary

One fixture represents one still-open issue across four logical episodes:

1. Episode 1 introduces a target Claim plus live support and contradiction branches.
2. Episode 2 contains no admissible resolving Evidence and tests premature closure.
3. Episode 3 supplies a frozen resolution candidate that is either fully admissible or deliberately fails at least one rule.
4. The scorer asks for the historical open state and the legal post-candidate status.

Each fixture has exactly one independently addressable OpenIssue. The two pilot domains are software-project memory and a personalized multi-session assistant. All names, IDs, text and labels are synthetic.

## Required frozen labels

Annotators must record, without reading any compressor output:

- `issue_id`, `issue_type`, `target_claim_id` and live `status`;
- every live support and contradiction Evidence pointer;
- the exact discharge rule and validity-critical dependencies;
- required authority;
- the active Goal and all hard constraints;
- candidate Evidence target, rule/scope/authority checks and expected final status.

An Episode 3 candidate is admissible only when all three booleans—rule, scope and authority—are true. Missing information is not a positive label. An issue remains at its original open status otherwise.

## Adjudication rules

- Conflicting source branches stay distinct; annotators may not choose a winner.
- Episode 2 prose, recency and confidence never discharge an issue.
- A changed target, mismatched scope or insufficient authority makes resolution illegal.
- Empty dependencies are valid; they are not missing annotations.
- If source records cannot determine a field, reject the fixture instead of guessing.

For future human or real-project extensions, two annotators label independently and a third adjudicates exact-field disagreements before hashing the snapshot. This synthetic pilot uses programmatically frozen labels, so no inter-annotator agreement is claimed.

## Scoring independence

`research.ospc.scorer` reads only the frozen fixture label and normalized compressor output. Compressors do not call the scorer, modify labels or evaluate themselves. Primary metrics exclude `INFEASIBLE_UNDER_BUDGET` rows and always publish their denominator alongside the infeasible rate.

The normalized output is checked against `fixtures/output_schema.json`. Representation false closure,
decision false closure and unsupported claims are reported separately; identity, branch, pointer and
discharge preservation are not inferred from text similarity.
