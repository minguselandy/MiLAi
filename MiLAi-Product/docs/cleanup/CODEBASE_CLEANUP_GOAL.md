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

### 2026-09-21 — C2 policy/candidates merged

- Retrieval policy/candidates PR #6 Run #32：17 jobs success，composition PASS。
- PR #6 rebase merged；post-merge `main` 为
  `d4907816f3635911eb8bd1c3e0e9a90031d6d153`。
- post-merge Run #33：17 jobs success，composition PASS。
- local `main == origin/main`，working tree clean 后创建 `cleanup/02-retrieval-temporal`。

### 2026-09-21 — C2 temporal extraction started

- 本轮只移动 temporal query/candidate ordering pure helpers，不同时抽 selection 或 trace。
- 十六个移动 helper 的 AST 与 `d4907816f3635911eb8bd1c3e0e9a90031d6d153`
  中的原实现逐项一致。
- `milai.application.retrieval` 继续暴露原 temporal helper import；route、ranking、threshold、
  weight、reference-time 语义均未改动。

### 2026-09-21 — C2 temporal merged and selection extraction started

- Retrieval temporal PR #7 Run #34：17 jobs success，composition PASS。
- PR #7 rebase merged；post-merge `main` 为
  `a8c5b083c27c8581304216fc42adb58acca4e3fa`。
- post-merge Run #35：17 jobs success，composition PASS。
- 从该 exact green `main` 创建 `cleanup/03-retrieval-selection`；本轮只移动 Context budget、
  weighted set-cover 与 lexical MMR helper，不同时抽 acquisition、operators、assembly 或 trace。
- 九个移动 helper 的 AST 与 `a8c5b083c27c8581304216fc42adb58acca4e3fa`
  中的原实现逐项一致；旧 facade helper import 继续指向同一函数对象。
- Context budget、selection weights、sorting/tie-break 与 Reader semantic projection 均未改变。

### 2026-09-21 — C2 selection merged and acquisition extraction started

- Retrieval selection PR #8 Run #36：17 jobs success，composition PASS。
- PR #8 rebase merged；post-merge `main` 为
  `2cd1e655ebbc728a3f444c42776404d74bbb73b1`。
- post-merge Run #37 首次 langgraph 在依赖安装阶段因 PyPI 下载超时失败；单 job 重跑后
  最新 attempt 17 jobs success，composition PASS。该失败未进入项目测试执行。
- 从该 exact green `main` 创建 `cleanup/04-retrieval-acquisition`；本轮只移动 formation/raw
  result composition、acquisition envelopes 与 query-local evidence material helper。
- 六个移动 helper 的 AST 与 `2cd1e655ebbc728a3f444c42776404d74bbb73b1`
  中的原实现逐项一致；旧 facade import 继续指向同一函数对象。
- acquisition planning、execution、strict-operator 判定与 Evidence identity 语义均未改变。

### 2026-09-21 — C2 acquisition merged and operators extraction started

- Retrieval acquisition PR #9 Run #38：17 jobs success，composition PASS。
- PR #9 rebase merged；post-merge `main` 为
  `7a2e08cb7e83b543724ffc95d65d10fb3658f788`。
- post-merge Run #39：17 jobs success，composition PASS。
- 从该 exact green `main` 创建 `cleanup/05-retrieval-operators`；本轮只移动 compound-subject
  matching、scalar-state cover、accepted-input execution 与 operator provenance helper。
- 四个移动 helper 的 AST 与 `7a2e08cb7e83b543724ffc95d65d10fb3658f788`
  中的原实现逐项一致；Runtime testkit 与旧 facade import 保持兼容。
- operator family、operand authority、reranker/cover 规则与 provenance collection 均未改变。

### 2026-09-21 — C2 operators merged and assembly extraction started

- Retrieval operators PR #10 Run #40：17 jobs success，composition PASS。
- PR #10 rebase merged；post-merge `main` 为
  `a62a75fb2a526d9d654ab34851c5dfa5249b941a`。
- post-merge Run #41 首次 Lab fast 因既有 40ms total-deadline timing test 在共享 runner 负载下
  失败；仅重跑失败 job 后最新 attempt 17 jobs success，composition PASS。
- 从该 exact green `main` 创建 `cleanup/06-retrieval-assembly`；本轮只移动 governed result
  assembly、response payload、decision snapshot 与 accepted evidence/span projection helper。
- 十一个移动 helper 的 AST 与 `a62a75fb2a526d9d654ab34851c5dfa5249b941a`
  中的原实现逐项一致；旧 facade 与 Runtime testkit 私有兼容 import 保持同一函数对象。
- route、reranking、Context budget、decision/evidence identity 与 response schema 均未改变。

### 2026-09-21 — C2 assembly merged and baseline hardening completed

- Retrieval assembly PR #11 merged；post-merge `main=e4d2d714f005bd0163584eb8634b55ddc09287b6`。
- post-merge Run #43 的 Product、integrations、Archive 与四个 replay shard 均通过，但 Lab fast
  暴露 40ms whole-request deadline 竞态，composition 因依赖失败而未建立。
- PR #12 将 reservation 语义改为确定性注入 `DeadlineExpired` 的测试证据；PR Run #44 与
  post-merge Run #45 最终均为 17 jobs success、composition PASS。
- PR #13 修复两个 active Product-05 runner 对旧 wildcard listen contract 的依赖；PR Run #46
  与 post-merge Run #47 均全绿。
- PR #14 建立 active `tools/` Product dependency inventory 与 no-new-private-dependency gate；
  PR Run #48 与 post-merge Run #49 均全绿。
- C2 trace extraction 从 exact green
  `d23c420f3054398b946eb1a51f5e6045f3c50632` 恢复。

### 2026-09-21 — C2 trace extraction and bounded finalization implemented

- 本轮只移动 matched replay、public acquisition trace、execution stage、latency/cost 与
  access-trace serialization helper，并将 final decision、acquisition-state transition、
  abstention、trace persistence 与 response/receipt assembly 抽成一个有界 finalization phase。
- 十一个函数、`_LegacyReplayPrefix` 与 `_EXECUTION_STAGE_BY_OPERATION` 均与 `d23c420...`
  基线 AST 一致；旧 `milai.application.retrieval` helper/type import 保持兼容。
- `_finalize_execution()` 内的原执行语句与 extraction 前 AST 一致；`retrieve()` 继续作为唯一
  public orchestration entry，search/acquisition/gate 顺序未改。
- trace schema、stage mapping、stop/fallback reason、timing/cost arithmetic 与 response wire
  均未改变。

### 2026-09-21 — Cleanup execution cadence adjusted

- 开发提交采用 targeted tests、Ruff、mypy 与 contract snapshot/compatibility checks。
- 每个 subsystem PR 只在最终候选执行一次完整 17-job composition；历史 replay 保留在 PR
  最终候选、merge queue 与 nightly，不再为每组 helper 单独重复运行。
- 后续以中等规模 subsystem PR 推进：Memory Context、MCP、OpenWorker 各计划两轮；不再按
  单组 helper 创建 PR。
- 合并目标是由 merge queue 验证最终 merge tree；在 required check 与 merge queue 已覆盖
  同一 merge tree 时，不再机械重复 post-merge 全套。

### 2026-09-21 — Retrieval subsystem merged; backup test determinism follow-up

- Retrieval trace/finalization PR #15 的 Run #51 最新 attempt：17 jobs success，composition
  实际 PASS；合并后的 `main=c96eb170776e9f29d575c2001fc77de15381af14`。
- Run #51 首次 Runtime attempt 与此前 Run #45 相同，唯一失败为 backup test 在
  `Database.close()` 返回后立即观察到尚未从 PostgreSQL 消失的 pool session；单 job 重跑
  通过，远端其余 `1240 passed / 3 skipped` 未受影响。
- 后续 test-only 修复只在测试 setup 中等待 API/Steward/Worker sessions 确认归零；不修改
  `Database.close()`、backup quiescence gate 或任何 Product 行为，原 pytest node ID 保持不变。

## Completion rule

只有总指令第 24 节全部条件有当前权威证据时，才把本 Goal 标记为 COMPLETE。
