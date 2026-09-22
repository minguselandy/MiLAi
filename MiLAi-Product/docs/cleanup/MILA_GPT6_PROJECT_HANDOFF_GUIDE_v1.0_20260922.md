---
document_id: MILAI-GPT6-PROJECT-HANDOFF-01
version: v1.0
date: 2026-09-22
status: READY_FOR_GPT6_HANDOFF
target_model: gpt-6-astra
source_goal: docs/cleanup/MILA_POST_CLEANUP_DEVELOPMENT_GOAL_v1.0_20260922.md
repository: minguselandy/MiLAi
github_url: https://github.com/minguselandy/MiLAi
open_pull_request: 27
paused_work_package: 3A-0_STATUS_RECONCILIATION_SUBMITTED_PENDING_REMOTE_CLOSURE
next_unstarted_work_package: 3A-1_WORKER_ONCE_REVALIDATION
new_experiment_allocations: 0
new_model_requests: 0
---

# MiLAi 迁移至 GPT-6 项目接手指导 v1.0

## 0. 目的

本文档用于把 `MILAI-POST-CLEANUP-DEVELOPMENT-01` 的执行工作交给 GPT-6 Astra。它提供：

- 当前 Git/GitHub、PR、CI 和 Goal 停点；
- 权威文件读取顺序；
- 如何从 GitHub 获取项目、提交分支和创建 PR；
- 如何安全完成尚未闭环的 PR #27；
- GPT-6 恢复开发时必须遵守的测试、证据和实验边界；
- 下一工作包 3A-1 的准入条件，但不授权在暂停期间执行它。

这次迁移是“开发代理/会话迁移”，不是 MiLAi Product 的模型 API 迁移。未经新的用户指令，
不得修改 Product/Lab 中的模型名称、Provider、API endpoint、Prompt、推理参数或实验配置。

---

# 1. GPT-6 target and operating guidance

目标模型保持用户指定的：

```text
gpt-6-astra
```

官方 OpenAI 文档入口：

- [Using GPT-6 Astra / model guidance](https://developers.openai.com/api/docs/guides/latest-model)

与本项目接手直接相关的官方迁移要点：

1. GPT-6 Astra 对长指令、skills 和 `AGENTS.md` 更敏感；接手前必须检查适用范围和优先级，
   不得把历史文档里的旧执行状态当成当前命令。
2. GPT-6 在编码任务上可能倾向运行更广测试；本项目必须遵守 Goal 的 L0–L4 风险分级，
   小改动不重复 full suite。
3. GPT-6 应保持行动连续性，但用户的暂停、停止、实验预算和外部写入边界优先。
4. 若未来另有指令把 MiLAi 应用本身迁移到 GPT-6 API，才按官方指南评估 Responses API、
   reasoning effort 和参数兼容性；本 handoff 不包含该类代码改动。

推荐接手方式：

```text
model: gpt-6-astra
reasoning: preserve the environment's effective setting;
           use a higher setting only when the user/environment explicitly selects it
```

不要为了“使用 GPT-6”改写仓库中冻结的历史 solver/model 字段。历史实验使用什么模型，仍按原
manifest 和结果记录。

---

# 2. Authoritative paused snapshot

## 2.1 Repository baseline

```text
Repository:                    minguselandy/MiLAi
GitHub:                        https://github.com/minguselandy/MiLAi
main at phase start:           dfeb359d2301b99c0125d9e54e9c29a9025d7f59
main Git tree:                 8b08c84e8d13d82e513034d690be057dc159722b
Product manifest files:        422
Product manifest SHA-256:      7927bb6a0cad2ed139a7ce05f34f64cd47e3c0cd75bb77ff431a433b83c0c693
Product tree SHA-256:          7135d3388f9360ab3acf7b160ad20451da1883a09d10bf7f51ac9a404942f521
Conformance:                   10 PASS / 34 UNVERIFIED / 0 DEVIATION
TECH_DEBT:                     5 FIXED / 5 NEEDS_REVALIDATION / 0 OPEN
Cleanup full workflow:         Run #60 / 35632657133 / 17 jobs PASS
Schema:                        0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
```

这些是 3A-0 的注册基线。GPT-6 恢复时必须先从 GitHub 读取 live `main`；如果 main 已变化，记录
新 commit/tree 和变更来源，不能静默继续使用旧 SHA。

## 2.2 Paused PR state

```text
Branch:                        docs/post-cleanup-status-reconciliation
PR:                            #27
PR URL:                        https://github.com/minguselandy/MiLAi/pull/27
Pre-handoff candidate:         e31baf3ff88151e6d7aa9692cba715d562991269
Last observed fast run:        35671618962
Last observed run status:      in_progress
Observation time boundary:     before user pause on 2026-09-22
Full-composition label:        must remain absent
Merge state at pause:          not merged
```

本 handoff 文档的提交会推进 PR head，所以 `e31baf3…` 只能作为暂停前快照。恢复时必须读取 PR #27
的 live head 和与该 head 对应的最新 workflow，不得根据本页猜测 CI 已成功。

## 2.3 Work-package truth

3A-0 已完成：

- 文档实现；
- Goal/roadmap 纳入候选；
- 本地 L0；
- Product manifest 422 files PASS；
- 13 receipts / 0 current failures；
- Conformance fresh / overall `UNVERIFIED`；
- repository boundary 4,360 tracked paths / 0 findings；
- 提交并打开 PR #27。

3A-0 尚未完成：

- live head fast CI 成功确认；
- expected-head merge；
- candidate/merge tree identity；
- post-merge `main == origin/main`；
- main push identity fast gate。

因此 Goal ledger 中 3A-0 必须保持 `IN_PROGRESS`，直到上述远端闭环完成。

3A-1 完全未开始。没有 worker 行为修改、PostgreSQL 执行或 revalidation receipt。

---

# 3. Mandatory reading order for GPT-6

GPT-6 必须按顺序读取，不能只读本 handoff 后直接编码：

1. `AGENTS.md`
2. `SOURCE_OF_TRUTH.md`
3. `MiLAi-Product/AGENTS.md`
4. `MiLAi-Lab/AGENTS.md`
5. `MiLAi-Product/docs/cleanup/MILA_POST_CLEANUP_DEVELOPMENT_GOAL_v1.0_20260922.md`
6. `MiLAi-Product/docs/cleanup/MILA_POST_CLEANUP_DEVELOPMENT_ROADMAP_v1.0_20260922.md`
7. 本文档
8. `MiLAi-Product/docs/PRODUCT_CURRENT_STATUS.md`
9. `MiLAi-Product/docs/PRODUCT_GOALS.md`
10. `MiLAi-Lab/docs/LAB_CURRENT_STATUS.md`
11. `MiLAi-Lab/docs/LAB_GOALS.md`
12. `MiLAi-Product/docs/TECH_DEBT.md`
13. GitHub PR #27 的 live head、files、labels、checks 和 merge state

读取后先写出以下事实的核对结果：

```text
current branch/main/head
PR #27 live head and base
latest workflow for that exact head
whether full-composition label is absent
whether worktree is clean
3A-0 remaining closure actions
3A-1 still not started
```

历史报告里的“current”“active”“running”只对其时间点有效。只有顶部 current-status、执行 Goal、
live GitHub 和真实进程句柄能证明现在仍在运行。

---

# 4. Accessing the project through GitHub

## 4.1 Read-only access

仓库为公开仓库时，可直接使用 HTTPS：

```bash
git clone https://github.com/minguselandy/MiLAi.git
cd MiLAi
git remote -v
git fetch origin --prune
git rev-parse origin/main
```

只读检查不需要把 token 写入仓库或命令参数。

## 4.2 Authenticated write access

提交分支需要对 `minguselandy/MiLAi` 有写权限。优先使用已配置的 SSH：

```bash
git clone git@github.com:minguselandy/MiLAi.git
cd MiLAi
ssh -T git@github.com
git remote -v
```

也可以在安装 GitHub CLI 的环境中使用：

```bash
gh auth login
gh auth status
```

安全规则：

- 不把 GitHub token、SSH private key 或 credential 写入仓库、`.env`、文档或 shell history；
- 不把 token 嵌入 remote URL；
- 使用系统 credential helper、SSH agent、GitHub App/connector 或临时环境凭证；
- 凭证失败时停止外部写入，仍可进行只读诊断。

## 4.3 Open the existing handoff branch

新 checkout：

```bash
git fetch origin --prune
git switch --track origin/docs/post-cleanup-status-reconciliation
git status --short
git rev-parse HEAD
```

本地已有分支：

```bash
git switch docs/post-cleanup-status-reconciliation
git pull --ff-only origin docs/post-cleanup-status-reconciliation
git status --short
git rev-parse HEAD
```

如果工作区不干净，不得 reset、checkout 或覆盖未知改动。先区分用户改动与该 Goal 改动；无法安全
分离时向用户报告。

## 4.4 Inspect PR #27

浏览器：

```text
https://github.com/minguselandy/MiLAi/pull/27
```

安装了 `gh` 时：

```bash
gh pr view 27 --repo minguselandy/MiLAi
gh pr checks 27 --repo minguselandy/MiLAi
```

Codex GitHub connector 可读取 PR、workflow runs 和 jobs。读取时必须使用 live PR head SHA 查询，
不要只按 branch 名或旧 run ID 判断。

---

# 5. Submitting work to GitHub

## 5.1 One work package per branch/PR

每个 Goal work package 使用独立 branch 和 PR。正常流程：

```bash
git fetch origin main
git switch main
git merge --ff-only origin/main
git switch -c <goal-scoped-branch>
```

编辑后只 stage 明确路径：

```bash
git status --short
git diff --check
git add <explicit-path-1> <explicit-path-2>
git diff --cached --check
git diff --cached --stat
git commit -m "<scope>: <bounded outcome>"
git push -u origin <goal-scoped-branch>
```

禁止：

```text
git add -A without reviewing scope
git reset --hard
git checkout -- user-owned paths
force-push shared branches
direct push to main
```

在自己尚未被他人更新的 PR branch 上 amend 后，只有先确认 remote head 仍是预期 SHA，才可以
`git push --force-with-lease`；不得使用裸 `--force`。

## 5.2 Create a pull request

GitHub 网页：

```text
https://github.com/minguselandy/MiLAi/compare/main...<branch>?expand=1
```

GitHub CLI：

```bash
gh pr create \
  --repo minguselandy/MiLAi \
  --base main \
  --head <branch> \
  --title "<work-package title>" \
  --body-file <reviewed-pr-body-file>
```

PR body 至少包含：

```text
Goal/work-package ID
scope and non-scope
behavior/API/schema/permission/canonical impact
exact validation commands/results
unrun checks and why
receipt/evidence identities
known risks/debt
model/experiment requests and usage, even when zero
```

## 5.3 CI labels

- docs-only：不加 `full-composition`；
- Lab-only 且 Product executable tree 未变：不加 full label；
- material Product behavior final candidate：按 Goal 在 exact tested head 上最多添加一次；
- metadata follow-up 前移除 full label，避免同一 executable tree 重跑；
- 不把旧 head 的绿色 workflow 用作新 head 的证据。

## 5.4 Merge with tested-head protection

合并前记录：

```bash
git rev-parse HEAD
git rev-parse HEAD^{tree}
```

GitHub connector/API merge必须提供 `expected_head_sha`。使用 squash/rebase 后，拉取 main 并证明
候选与 merge tree 相同：

```bash
git fetch origin main
git rev-parse <tested-head>^{tree}
git rev-parse origin/main^{tree}
git diff --quiet <tested-head> origin/main
```

然后同步本地：

```bash
git switch main
git merge --ff-only origin/main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
git status --short
```

最后等待该 merge commit 对应的 main fast identity gate。只有这些全部通过，工作包才可标 `PASS`。

---

# 6. Exact resume protocol for PR #27

GPT-6 获得恢复指令后，必须按此顺序：

1. 从 GitHub 读取 PR #27 的 live head、base、labels、mergeable state；
2. 查询该 exact head 的所有 PR-triggered workflow；
3. 确认只有应有的 fast workflow，且 `full-composition` 未实际启动；
4. 若 latest exact-head fast run 仍在执行，只轮询同一 run；不要重启；
5. 若 fast success，重新读取 PR head，防止检查后 head 被推进；
6. 使用 live head 作为 `expected_head_sha` squash merge；
7. fetch `origin/main`，比较 candidate tree 与 merge tree；
8. fast-forward 本地 main，证明 `main == origin/main`、worktree clean；
9. 等待 merge commit 对应的 main fast identity run 成功；
10. 从新的 exact main 创建 3A-1 branch；
11. 在 3A-1 的首个提交中把 Goal ledger 的 3A-0 改为 `PASS`，记录 PR/run/merge/tree identity，
    并把 3A-1 改为 `IN_PROGRESS`。

如果 PR #27 的 live head、base 或 files 与本文快照不一致，先审查差异。不能为了快速合并而覆盖
其他协作者提交。

---

# 7. Next work package: 3A-1, not yet authorized during pause

工作包：Worker `--once` Revalidation。

目标问题：

> `milai-worker --once` 是否真实实现一次 bounded worker cycle，并在 empty queue、bounded work、
> failure、`--check` 和 watermark 情况下有准确退出合同？

候选合同：

```text
startup
→ settings/dependency initialization
→ blob orphan reconciliation
→ one bounded worker cycle
→ watermark reconciliation when applicable
→ database close
→ exit
```

必需 case：

```text
empty queue
queue below limit
queue above limit
multiple projections
orphan exists
no projection work
processing failure
--check does not lease/process
watermark work
```

queue、lease、watermark、orphan 和退出码必须由真实 PostgreSQL 证据关闭；mock 不能替代。

预期输出：

```text
MiLAi-Product/docs/revalidation/worker-once/REVALIDATION.md
MiLAi-Product/docs/revalidation/worker-once/receipt.json
MiLAi-Product/docs/revalidation/INDEX.md
MiLAi-Product/docs/TECH_DEBT.md
```

先诊断，不预设缺陷。合法分类：行为/文档一致 → FIXED；行为正确但文档 drift → 修文档后 FIXED；
不再适用 → OBSOLETE；可重复行为/安全缺口 → OPEN 并另开 remediation Goal/PR。

暂停状态下不得执行本节。只有用户明确恢复开发且 PR #27 已完成远端闭环后才能开始。

---

# 8. Validation discipline for GPT-6

```text
L0 docs/static:
  parse, links, diff check, manifest, receipts, Conformance, boundary
  no pytest/full

L1 targeted:
  changed-module Ruff/mypy + exact adjacent nodes

L2 affected package:
  package static/tests/build + Product evidence gates

L3 root fast CI:
  path-classified jobs only

L4 full composition:
  one exact high-risk final candidate only
```

不要因为 GPT-6 可以执行更长任务而扩大验证。只有风险、失败或未解决问题才允许升级测试层级。
相同 executable tree 不重复 full composition。

---

# 9. Hard prohibitions during handoff

```text
do not resume historical experiments
do not start model/Provider/Judge calls
do not allocate tokens/generations
do not enter 3A-1 before PR #27 closes
do not modify Frozen Architecture
do not rewrite migration 0001–0049
do not change Product default retrieval/ranking/threshold/budget/prompt
do not treat EXPOSED as USED
do not rewrite historical receipts/results
do not use old green CI for a new head
do not run broad tests for documentation changes
```

---

# 10. Suggested first prompt for GPT-6

将以下文本与仓库路径一起交给 GPT-6：

```text
详细阅读并继续执行
/cra/memory/mx_memory/MiLAi/MiLAi-Product/docs/cleanup/
MILA_GPT6_PROJECT_HANDOFF_GUIDE_v1.0_20260922.md
以及其 source_goal。

先按文档顺序读取 AGENTS.md、SOURCE_OF_TRUTH.md、Product/Lab AGENTS 和 Goal。
从 GitHub 读取 PR #27 的 live head、checks、labels 和 merge state，不依赖暂停快照。
先完成 PR #27 的 tested-head/merge/main identity 闭环；没有完成前不得开始 3A-1。
遵守 L0–L4 最小充分验证，不重复长测试，不恢复历史实验，不分配模型请求。
每完成一个 work package，提交独立 GitHub PR，并记录 exact candidate/merge identity。
```

如果 GPT-6 所在环境没有 `/cra/memory/mx_memory/MiLAi`，先按第 4 节从 GitHub clone，再把绝对路径
替换为新 checkout 的实际路径。

---

# 11. Handoff acceptance checklist

```text
[ ] target model is gpt-6-astra
[ ] repository cloned/fetched from minguselandy/MiLAi
[ ] root/Product/Lab AGENTS and SOURCE_OF_TRUTH read
[ ] source Goal and roadmap read completely
[ ] PR #27 live state queried
[ ] no old workflow status treated as current
[ ] no historical experiment resumed
[ ] no new model allocation created
[ ] PR #27 exact-head fast gate verified
[ ] PR #27 merged with expected-head protection
[ ] candidate/merge tree identity verified
[ ] post-merge main identity fast gate verified
[ ] Goal updated: 3A-0 PASS, 3A-1 IN_PROGRESS only after closure
[ ] 3A-1 begins from exact latest main
```

完成本 checklist 前，不得声称迁移或 3A-0 已闭环。
