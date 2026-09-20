# MiLAi codebase cleanup execution goal

## Identity

```text
Contract: MiLAi 全仓代码整理与模块化重构执行总指令 v1.0
Goal thread: 01a0aad3-4faf-7871-b825-8ddb3cf177be
Status: ACTIVE
Baseline: 798b7cac21957873791afff6122d3f06a82214c5
Baseline workflow: Run #29 / 35519772754 / attempt 2
```

## Objective

在不改变 Product、Lab、Archive 顶层边界和已发布行为合同的前提下，分责任域完成
Runtime Retrieval、Memory Context、MCP、OpenWorker Host、测试与 Lab active code 的有界
模块化；随后刷新最终 Product tree 的五项行为证据，并以全仓 composition PASS、
`main == origin/main` 和 clean worktree 收尾。

本 Goal 只建立可维护 seam，不实现新的 State、Attention、Utility、Revision、Transfer 或
Host Continuity 机制。

## Immutable boundaries

- `architecture/v1.0/**`、Product/Lab/Archive 顶层结构不修改。
- public Runtime API、MCP tool/schema、CLI、HTTP contract、import path 不修改。
- DB migration、retrieval/ranking/threshold/weight、Context budget、Prompt、权限和 token
  semantics 不修改。
- Lab treatment、sealed fixtures/labels/config/results、`studies/archive/**` 与 Artifact Archive
  历史 bytes 不修改。
- 不做 dependency upgrade、全仓 formatter sweep、大规模 rename 或跨 subsystem 巨型 PR。
- receipt 引用的 pytest node ID 必须保留；历史 receipt 不覆盖、不改写。
- 发现真实行为缺陷时停止结构 PR，登记 TECH_DEBT/issue，并转独立 behavior Goal/PR。

## Phase ledger

| Phase | Scope | Status |
| --- | --- | --- |
| C0 | Baseline + inventory | COMPLETE |
| C1 | Safe hygiene | COMPLETE — no deletion qualified |
| C2 | Runtime Retrieval modularization | IN PROGRESS |
| C3 | Runtime Memory Context modularization | PENDING |
| C4 | MCP Server modularization | PENDING |
| C5 | OpenWorker Host modularization | PENDING |
| C6 | Test organization | PENDING |
| C7 | Lab active code organization | PENDING |
| C8 | Dead-code / compatibility audit | PENDING |
| C9 | Current-tree evidence refresh | PENDING |
| C10 | Final cleanup baseline | PENDING |

## PR discipline

每个 PR 只处理一个责任域；至少运行 affected package 的 Ruff、mypy、unit/integration tests
与 build。Product 改动还必须重建并检查 manifest、boundary、conformance 和 receipt。
远端 Runtime、identity、Conformance、Archive、六个 integrations、Lab fast、四个 replay 与
composition 全部 PASS 后才合并。

## Required final evidence

- 四个 Product 热点完成有界拆分且 public imports/CLI/MCP/HTTP contract 保持；
- receipt pytest node ID 全部存在；
- Lab archive/sealed bytes 未变化，active runner 开始 thin-runner 化；
- compatibility/dead-code audit 有引用证据；
- 五项 FIXED TECH_DEBT 在最终 Product tree 上重新执行并生成独立 post-cleanup receipts；
- final module map、cleanup results、final baseline 落盘；
- 最终远端 17 jobs success、composition PASS、`main == origin/main`、working tree clean。

## Execution journal

### 2026-09-20 — Goal registered

- 总指令 v1.0 设为唯一 cleanup 执行合同。
- 仓库外先建立 Goal 总账，避免污染 PR #4。

### 2026-09-21 — C0 hard gate established

- PR #4 Run #28：17 jobs success，composition PASS；随后 rebase merged。
- post-merge `main`：`798b7cac21957873791afff6122d3f06a82214c5`。
- Run #29 首次 Lab fast 因 40ms deadline timing test 在 RESERVED 前超时而失败；同一代码的
  PR run 已通过。仅重跑失败 job 后 Lab fast 通过，composition 实际 PASS。
- local `main` fast-forward 到 exact remote HEAD，clean worktree 后创建
  `cleanup/00-baseline-inventory`。
- C0 只增加 identity/inventory，不进行 production refactor。

### 2026-09-21 — C0 merged and post-merge green

- C0 PR #5 Run #30：17 jobs success，composition 实际 PASS。
- PR #5 rebase merged；post-merge `main` 为
  `b59bffd646a9d3cb6092ed576bd1e2a43c14a9b6`。
- post-merge Run #31：17 jobs success，composition 实际 PASS。
- local `main == origin/main`，working tree clean 后创建
  `cleanup/01-retrieval-policy-candidates`。

### 2026-09-21 — C1 safe hygiene review

- 复核 active production/test/import/receipt/CLI/Lab inventory。
- 没有对象同时满足“无 production、test、contract、receipt、entrypoint、Lab 引用”的删除
  门槛；本阶段不删除代码、不删除 compatibility facade，也不单独创建 hygiene PR。
- 真实清理继续采用 need-driven extraction；C8 再做完整 compatibility/dead-code 分类审计。

### 2026-09-21 — C2 Retrieval extraction started

- 从 exact green `b59bffd646a9d3cb6092ed576bd1e2a43c14a9b6` 开始首个 Retrieval PR。
- 首轮范围仅为 `retrieval_core/policy.py` 与 `retrieval_core/candidates.py`；
  `RetrievalService`、acquisition、temporal、selection、assembly、trace 均未改动。
- 九个移动 helper 的 AST 与原实现逐项一致；旧 `milai.application.retrieval` helper import
  继续由 facade 暴露。

## Completion rule

只有总指令第 24 节全部条件有当前权威证据时，才把本 Goal 标记为 COMPLETE。
