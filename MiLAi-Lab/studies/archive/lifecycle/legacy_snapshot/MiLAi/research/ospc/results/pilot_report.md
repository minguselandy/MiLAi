# OSPC deterministic pilot result

> Schema `0.1.x EXPERIMENTAL`  
> Implementation `CANDIDATE`  
> `NO-GO FOR SCHEMA FREEZE`

Decision: **ABANDON novelty claim**.

Primary metrics exclude explicit infeasible rows; infeasible rate is always reported beside them. 
A method therefore cannot turn an insufficient budget into a zero-false-closure success.

| method | feasible | identity | branches | pointers | representation FC | decision FC | unsupported | resolution | task success | tokens mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_raw_context | 16/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 233.4 |
| naive_recursive | 32/40 | 0.0 | 0.0 | 0.0 | 1 | 1 | 1 | 0.5 | 0.25 | 230.4 |
| extractive_top_k | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 244 |
| hierarchical_summary | 32/40 | 1.0 | 0.0 | 0.0 | 0 | 0 | 0 | 0.5 | 0.75 | 192 |
| structured_eviction | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 244 |
| typed_state | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 244 |
| static_open_issue | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 244 |
| ospc | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 244 |
| ospc_no_protected | 32/40 | 0.0 | 0.0 | 0.0 | 1 | 1 | 1 | 0.5 | 0.25 | 148.8 |
| ospc_no_discharge | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 0.5 | 0.75 | 234.4 |
| ospc_no_branches | 32/40 | 1.0 | 0.0 | 0.0 | 0 | 0 | 0 | 0.5 | 0.75 | 202 |
| ospc_no_validator | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 244 |
| oracle_equal_budget | 32/40 | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 1 | 1 | 244 |

## Cost and failure distributions

| method | charged p50/p95 | wall ns p50/p95 | CPU ns p50/p95 | GPU ns | recovery/fallback/model | failures |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| full_raw_context | 120/410 | 188572/257016 | 179980/247174 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=24 |
| naive_recursive | 256/260 | 331327/437206 | 323439/421054 | 0 | 0/0/0 | BRANCH_LOSS=32, DECISION_FALSE_CLOSURE=32, DISCHARGE_LOSS=32, IDENTITY_LOSS=32, INFEASIBLE_UNDER_BUDGET=8, LEGAL_RESOLUTION_MISS=16, REPRESENTATION_FALSE_CLOSURE=32, UNSUPPORTED_CLAIM=32 |
| extractive_top_k | 267/299 | 511517/652038 | 503391/639886 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=8 |
| hierarchical_summary | 209/211 | 150019/158679 | 142692/151639 | 0 | 0/0/0 | BRANCH_LOSS=32, DISCHARGE_LOSS=32, INFEASIBLE_UNDER_BUDGET=8, LEGAL_RESOLUTION_MISS=16 |
| structured_eviction | 267/299 | 120127/138565 | 112344/128836 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=8 |
| typed_state | 267/299 | 118450/153931 | 110426/145464 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=8 |
| static_open_issue | 267/299 | 116774/136331 | 109185/128089 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=8 |
| ospc | 267/299 | 124877/149181 | 117499/139845 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=8 |
| ospc_no_protected | 155/157 | 100292/117054 | 92451/109274 | 0 | 0/0/0 | BRANCH_LOSS=32, DECISION_FALSE_CLOSURE=32, DISCHARGE_LOSS=32, IDENTITY_LOSS=32, INFEASIBLE_UNDER_BUDGET=8, LEGAL_RESOLUTION_MISS=16, REPRESENTATION_FALSE_CLOSURE=32, UNSUPPORTED_CLAIM=32 |
| ospc_no_discharge | 255/287 | 117054/172927 | 109202/163649 | 0 | 0/0/0 | DISCHARGE_LOSS=32, INFEASIBLE_UNDER_BUDGET=8, LEGAL_RESOLUTION_MISS=16 |
| ospc_no_branches | 221/224 | 112863/150019 | 105034/140997 | 0 | 0/0/0 | BRANCH_LOSS=32, INFEASIBLE_UNDER_BUDGET=8, LEGAL_RESOLUTION_MISS=16 |
| ospc_no_validator | 267/299 | 118172/134096 | 110470/126723 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=8 |
| oracle_equal_budget | 267/299 | 119848/167340 | 112384/157831 | 0 | 0/0/0 | INFEASIBLE_UNDER_BUDGET=8 |

## Hard-falsifier result

- `HF-01_STRONG_TYPED_STATE_EQUIVALENT`
- `HF-02_STATIC_OPEN_ISSUE_EQUIVALENT`
- `HF-06_VALIDATOR_COST_WITHOUT_MEASURED_GAIN`

The strongest typed-state and the static always-protect baseline match OSPC on every frozen 
primary equivalence field. OSPC also performs deterministic validation work without a measured 
task gain. This pilot therefore preserves the useful product invariant but abandons an OSPC 
novelty claim. It does not establish a general scientific impossibility result.

## Reproduction

```bash
runtime/.venv/bin/python -m research.ospc.generate_fixtures
runtime/.venv/bin/python -m research.ospc.run_benchmark
runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v
```

Fixture SHA-256: `8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a`  
Scorer: `ospc.scorer.v1`  
All fixtures are synthetic; model calls, recovery calls and production credentials are zero.
