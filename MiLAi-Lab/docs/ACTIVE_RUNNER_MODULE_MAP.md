# Active Runner Module Map

## Scope

C7 establishes the first bounded thin-runner cohort for active Lab code. It moves the
implementation of two self-contained Product experiment runners into the installable
`milai_lab` package while retaining their historical executable paths:

| Compatibility path | Implementation owner | Responsibility |
| --- | --- | --- |
| `tools/run_product02_context_gate.py` | `src/milai_lab/runners/product02_context_gate.py` | Product-02 context-gate dataset, arm execution, scoring, and result serialization |
| `tools/run_product03_openworker_usability.py` | `src/milai_lab/runners/product03_openworker_usability.py` | Product-03 OpenWorker flow/load execution and result serialization |

The compatibility files are 16-line import-and-exit wrappers. They re-export the implementation
module's non-dunder names so existing direct imports from `tools/` continue to resolve to the same
objects. Direct script invocation still delegates to the original `main` implementation.

This is deliberately an initial cohort, not a claim that every historical Lab runner has been
rewritten. The remaining runner inventory contains coupled experiment families and references from
sealed or historical evidence. Those files require separate dependency-group review before any
move. C7's cleanup success condition is to begin the active-runner pattern without changing study
contracts or broadening the Product/Lab boundary.

## Compatibility invariants

The extraction preserves:

- CLI option names, defaults, subcommands, parsing, exit behavior, and output paths;
- dataset selection and ordering;
- arm labels, prompts, budgets, provider calls, scoring, metrics, and output schemas;
- the downstream `run_product03_opportunity_probe.py` imports of `_dataset_path` and
  `_load_population`;
- the historical `tools/run_*.py` filesystem entrypoints;
- the Lab-to-Product dependency boundary.

No file under `data/fixtures/`, `data/manifests/`, `studies/archive/`, or the Product tree is changed
by this extraction.

## Structural evidence

Against base `9ff549e8a02ec2ed1a08d65edcbc91679177b144`, recursive AST comparison reports:

| Runner | Baseline definitions | AST-identical definitions | Missing definitions |
| --- | ---: | ---: | ---: |
| Product-02 context gate | 31 | 31 | 0 |
| Product-03 OpenWorker usability | 18 | 18 | 0 |

The only path-sensitive implementation adjustment is the Product-02 `ROOT` calculation: the
implementation moved three directories below the Lab root, so it now uses `parents[3]`. Its value
remains the same Lab root. The former `sys.path` mutation became unnecessary because the runner now
lives in the installed package and was removed to satisfy the active-source boundary.

Strict typing required four annotations that do not alter runtime behavior: two assignment ignores
for pre-existing local type narrowing, one untyped third-party tokenizer call ignore, and one return
type ignore around the pre-existing native turn adapter.

## Direct verification

`tests/unit/test_active_runner_compatibility.py` checks:

- wrapper-to-implementation object identity for parser, execution, and `main` callables;
- frozen representative CLI defaults and subcommand parsing;
- Product-02 Lab-root identity;
- a maximum wrapper size of 20 lines;
- absence of top-level function or class definitions in compatibility wrappers.

C7 verification also includes changed-scope Ruff, strict mypy for `milai_lab.runners`, both CLI help
paths, downstream helper-import smoke, Lab boundary, and tools boundary. The Lab fast gate runs once
for the final PR candidate; historical replay and full composition remain reserved for C9/C10 unless
a real behavior-path risk is discovered.
