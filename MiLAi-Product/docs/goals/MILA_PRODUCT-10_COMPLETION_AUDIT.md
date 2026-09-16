---
document_id: MILA-PRODUCT-10-COMPLETION-AUDIT
version: "1.0"
status: PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
goal: MILA-PRODUCT-10@1.3
audited_at: "2026-09-04T02:05:50+08:00"
execution_authorized: true
formal_holdout_authorized: true
formal_holdout_consumed: false
product_behavior_changed: default_off_only
---

# Product-10 完成审计

## 唯一终态

```text
PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
```

X0--X2 已完成。两轮通用 B1 修复均未通过 H1，且 authority/scope/snapshot/Canonical 安全门没有
失败。因此 Goal 第 13 节终态优先级 2 先于 opportunity 不足命中；X3、X4 和 formal holdout
停止，不允许第三轮 case-driven 调参。

## 阶段与证据

| 阶段 | 结果 | 权威证据 |
| --- | --- | --- |
| X0 seal | `COMPLETE`：24 cases / 36 groups | membership SHA `be6f6bf9…447d9`；label SHA `629f89ee…b266` |
| label provenance | proxy / human `PENDING` / non-gold | Qwen3.6-35B-A3B-FP8 model-assisted labels |
| X1 trace | `COMPLETE_BEHAVIOR_NEUTRAL` | A0 `p10-a0-x1-20260904c`; 28/36, admission 4, not-discovered 9 |
| X2 round 1 | `FAIL_PRODUCT10_H1` | `p10-x2-matched-20260904a`; new 0, lost 1, mean `-0.02083` |
| X2 round 2 | `FAIL_PRODUCT10_H1` | `p10-x2-matched-20260904b`; new 3, lost 3, mean `+0.04167` |
| H1 full-case guard | `FAIL` | previously full-coverage cases lost 2: `1c0ddc50`, `27016adc` |
| X3 | `INSUFFICIENT_OPPORTUNITY` | audited opportunities A0/B1 = 1/2, required `>=6` |
| X4 | `NOT_ENTERED_BY_TERMINAL_PRECEDENCE` | H1/H2 mediator gate not satisfied |
| formal 500 | `NOT_SCORED` | files historically accessed; Product-10 scored cases = 0 |

Second-round matched A0 and B1 both covered `29/36` micro groups. B1 raised full-coverage cases from
19 to 20 and mean coverage from `0.84375` to `0.8854167`, but lost `1c0ddc50:g2`,
`27016adc:g1` and `gpt4_fe651585:g1`. The latter two were first lost at C50 because activation
thresholds `17,332` and `16,971` exceeded the fixed `16,384` Context budget; the first had been
A0-visible through adjacent hydration and became `NOT_DISCOVERED` when B1 changed its anchor set. The
three newly covered groups were the intended S43 admission losses. `1c0ddc50` and `27016adc` were
fully covered under A0 and became partial under B1; `gpt4_fe651585` lost a group but was already
partial under A0. Thus the pre-registered case-level guard is 2, while the group-level diagnostic is
3. This is budget/adjacency displacement, not an Evidence identity collapse.

## Run validity and safety

`p10-x2-matched-20260904b` passed:

```text
fresh PostgreSQL                         true
same A0/B1 candidate pool                true
candidate-pool mismatches                0
capture / projection                     11,893 / 11,893
isolated tenants                         true
automatic semantic retries               0
Reader / vLLM / votes                    0 / 0 / 0
recall-side Canonical mutation           0
trace written before labels loaded       true
run-owned database volume removed        true
formal cases scored                      0
```

Effect Product tree is `db355c3c322d4bbb79a0becde321112b5b5f9d75498ff281a3346e0dea276d6c`;
effect lock digest is `b55489f3e8c9d522465b47ee473064e8a3da3b40a5c988b217d0ff176d6674f7`.
The final Product delivery, including the MCP wrapper, is separately pinned by
`MiLAi-Lab/data/locks/product10-final-product.lock.json`: Product tree
`0b170d3fdeaf962c26492578293d29a7fcc1c9036555f8adb01b121f41cba7b5`, logical lock digest
`4bf9ee438c92a5c4545bbcd05e940136d6f0e477f89a10cf5366663640b6d68b`, verification `PASS`.
Artifact hashes:

```text
summary             6d4b1a8a293718429d270c7d744e5c4708f4f5dcb64866d175ea22f1a6cfeeba
redacted trace      a9408eb81d62ac0300fb2fccf5849fbe8e767add31f4bac4fd9cb2b4c44a8bb1
capture trace       65b24562636bc0f66e5ea0e620174369b81cbd2b42d952f753b3753b92ec0130
scoring view        ca045fe1c0b021451d1a67bcb26e46f408234e3c7e9c5cf8fe7f5ec1befba607
cleanup receipt     879691e662a66177768528b70882ae6a264ee901bf6fe61895adabfd9b9a976d
scoring correction v2  167ee99528ec291175c931596bf2a13108a3e806c1284503c1c8b177c7b18a9d
scoring correction v3  065812c5702a8bffa1ac05158a0f833268a597f65cfd478425f5ea4adb9b5659
```

The sealed summary is preserved byte-for-byte. Its original scorer counted coverage from rendered
identities but set per-group `covered` from upstream first-loss, undercounting one loss. A post-hoc
derived receipt over the same immutable trace and labels makes rendered adjacent-turn visibility
decisive, adds a contradiction fail-fast, and corrects lost groups from 2 to 3. Coverage, mean gain,
opportunity and terminal status are unchanged.

A second derived audit found that the runner encoded `lost_groups = 0` where the pre-registered H1
guard is `previously full-coverage cases lost = 0`. Correction v3 retains three lost groups as a
diagnostic, computes two regressed full cases, and changes the future runner threshold to the
case-level contract. Both old and corrected gates fail for this run, so no sealed effect or terminal
claim changes.

## Product disposition

- behavior-neutral X1 testkit and trace diagnostics are retained;
- B1 admission code is retained behind
  `MILAI_READER_INSTANCE_PRESERVING_ADMISSION_V0_1_ENABLED=false` and is not the production default;
- no continuation migration, procedure, capsule or assertion was fabricated;
- `milai-agent-memory-mcp` v0.1.1 is delivered as the fixed authenticated Streamable HTTP wrapper;
- public MCP tool schema remains `query` plus optional `previous_context_id`;
- future coverage work must reopen at representation/acquisition level as a new Goal.

## Verification

```text
Product focused unit/API-contract tests     105 passed
MCP full tests                              66 passed
Lab Product-10/manifest tests               14 passed
Product/Lab/MCP Ruff                        PASS
Product/Lab/MCP strict mypy                 PASS
Runtime sdist + wheel build                 PASS
MCP sdist + wheel build                     PASS
Lab sdist + wheel build                     PASS
wheel console-script inspection             PASS
MCP authenticated HTTP smoke                PASS (included in 66)
```

The separate Runtime database integration module requires externally supplied three-role database
URLs when invoked directly. Its 23 fixtures failed before test execution when those URLs were absent;
the sealed effect runner independently created, migrated, exercised and removed its own fresh
three-role PostgreSQL deployment, which is the database evidence claimed here.
