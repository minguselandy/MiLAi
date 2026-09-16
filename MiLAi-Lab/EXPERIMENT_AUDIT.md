---
document_id: MILA-LAB-PRODUCT09-INTEGRITY-AUDIT
version: "1.0"
status: PROVISIONAL_FAIL
reviewed_at: "2026-09-03T21:13:00+08:00"
review_independence: same-family
acceptance_status: provisional
overall_verdict: FAIL
reason_code: CLAIM_EVIDENCE_MISMATCH_AND_UNSEALED_EVALUATION
---

# Product-09 实验完整性审计（Product-10 继承门）

## 总判词

`FAIL / CLAIM_EVIDENCE_MISMATCH_AND_UNSEALED_EVALUATION`。

七个结果 JSON 均存在、可解析且汇总算术可复算；失败来自 claim-evidence fidelity、执行隔离和
run provenance。Product-09 的历史 `3/4 / 0.75` 只能作为 documentary observation，不能直接
成为 Product-10 的 audit-grade A0。Product-10 本身仍为 `PLANNED_NOT_STARTED`，没有方法结果。

本审计由 fresh reviewer 执行，但属于同模型家族，结论为 provisional，不构成 cross-family
acceptance。

## A. Ground-truth provenance — FAIL

- lifecycle target 是 runner 生成的 synthetic fact：
  `tools/run_product09_codex_lifecycle.py:249-267,574-612`；
- LME answer/reference 来自 hash-checked dataset：
  `tools/run_product09_codex_lme.py:25-28,49-87,259-297`；required sessions 来自 dataset
  `answer_session_ids`（`:103-117`）；
- turn targets 来自 `data/labels/product02-longmemeval-answer-turns-qwen36-v4.json:2-33,17250-17269`，
  是 Qwen
  model-assisted、zero-vote、未人工裁决 proxy；
- scorer 自述非 official LongMemEval score：`src/milai_lab/scorers/answers.py:35-60`；
- memory-only 依赖 prompt，不是 sandbox enforcement；Codex 仍有 read-only filesystem，trace 又
  只保留 completed `milai_memory_resolve`：
  `tools/run_product09_codex_lifecycle.py:366-388,403-424`。

分类：answer EM/F1 与 session coverage 是 `real_gt`；turn coverage 是 `synthetic_proxy`；
lifecycle 是真实本地基础设施上的 scripted synthetic smoke。

## B. Score normalization — WARN

- scorer 使用 NFKC/casefold、标点与 article removal；没有以 prediction 自身 max/min/mean 归一化：
  `src/milai_lab/scorers/answers.py:26-60`；
- `exact_match` 是 normalized EM，不是 literal equality；
- `all_answer_turn_recall=0.75` 实为“3/4 cases 全部 proxy turns 可见”，micro coverage 是 `6/7`：
  `var/product09/lme-002.json:2,24-103`，聚合实现见
  `tools/run_product09_codex_lme.py:449-471`。

## C. Result existence and claim fidelity — FAIL

全部七个文件存在并可复算，但有以下 material mismatch：

1. `database_restart_completed=true`（`var/product09/e2e-002.json:18`、
   `e2e-003.json:18`）实际只重启 API/worker/MCP；PostgreSQL 没有重启：
   `tools/run_product09_codex_lifecycle.py:673-682,809-817`；
2. “restart recall 2/2” 不成立：design 只在 restart 前查，restart 后只查 fix：
   `tools/run_product09_codex_lifecycle.py:645-702`；
3. study 对 state-update 的两次调用是 stale；`lme-002.json:84-102` 记录一次；
4. “formal 500 未访问”不成立；loader 读取完整 dataset/labels 后再选四例：
   `tools/run_product09_codex_lme.py:49-79`。只能声称“未执行 formal 500-case scoring run”；
5. cleanup success 在 teardown 前写入，且 teardown 使用 `check=False`：
   `tools/run_product09_codex_lifecycle.py:795,809-817`、
   `tools/run_product09_codex_lme.py:478,491-499`；
6. historical result 未携带 Product tree/lock、runner/input hashes、timestamp/command、Codex model
   identity/config 或 raw trace hash；当前 pin 通过不能追溯绑定历史 run；
7. Host-guidance result 没有 treatment text/hash/tree，单次 `3/4 -> 2/4` 只能描述为一次 recorded
   regression，不能作 causal claim；
8. P09-0 与 final-quality PASS 没有 durable command receipt。

## D. Dead code/output reachability — WARN

未发现 dead metric function，但 audit-critical evidence 被丢弃：stdout/stderr tails 未进入 summary，
scorer ID 未进入 case row，non-memory、failed、incomplete tool events 被 trace filter 移除。相关路径：
`tools/run_product09_codex_lifecycle.py:366-388,435-442`、
`tools/run_product09_codex_lme.py:296-297`。

## E. Scope — WARN

| family | N / runs | live Codex | claim ceiling |
| --- | --- | --- | --- |
| lifecycle | 1 harness failure + 2 successful repeats, one synthetic config | yes | local integration smoke；prompt-forced tool use |
| LME baseline | 4 named opened-dev cases, two non-equivalent iterations | yes | one normalized EM/F1 diagnostic；nonofficial scorer |
| COUNT localization | 1 case, 1 run | yes | mechanism localization only |
| Host guidance | 4 cases, 1 run | yes | recorded regression, not causal effect |
| Product-10 | 0 | no | no method/effect claim |

没有 seed、Codex model snapshot 或真实 replication policy。工具调用由 prompt 明确规定 exactly once
或 without tools：`tools/run_product09_codex_lifecycle.py:658-661,689-692,709,723-725`，不能主张
autonomous tool selection。

## F. Evaluation type — WARN

- `e2e-001`：`simulation_only`，harness failure；
- `e2e-002/003`：按审计 taxonomy 为 `simulation_only`，但使用真实本地服务和 Codex；
- LME answer EM/F1、required sessions：`real_gt`；
- answer-turn visibility：`synthetic_proxy`；
- 无 human eval、official LongMemEval judge 或 leaderboard-equivalent run。

## Claim impacts

| claim | disposition |
| --- | --- |
| Product-09 usable lifecycle | 仅支持单一 local synthetic config、prompt-forced calls、application-stack restart |
| PostgreSQL restart durability / 2-of-2 recall | unsupported |
| opened-dev `3/4 / 0.75` | numerically supported as normalized EM/F1 documentary observation |
| memory caused `3/4` | not auditable；filesystem isolation 与 raw trace 不足 |
| answer-turn recall `0.75` | rename 为 case-completion；micro proxy coverage `6/7` |
| formal 500 untouched | false literally；只支持 no formal 500-case scoring run |
| Host guidance caused regression | unsupported causal wording；one recorded run only |
| Product-10 H1/H2 | `NOT_RUN` |

## Product-10 继承决定

允许的最强表述：

> 一次 Product-09 run 在四个具名 opened-development case 上记录 normalized EM 3/4、mean
> normalized F1 0.75，使用非官方 deterministic scorer；500-case 文件被读取，但未执行 formal
> 500-case scoring run。

禁止把它写成 75% LongMemEval accuracy、memory causal effect、audit-grade A0，或任何 Product-10
方法证据。X0 获授权后必须用 enforced tool isolation 和 sealed code/input/run provenance 重跑 A0。

## Required actions

1. P10 X0 run bundle 绑定 Product tree/lock、Lab runner、dataset/selection/label hashes、命令、时间、
   exact Codex identity/config、完整 redacted trace 与 checked cleanup receipt；
2. 禁用非 memory tools 和数据文件访问；任何额外、失败或未完成 tool event 均 fail closed；
3. 显式区分 normalized EM、case-completion 和 micro turn coverage，并标记 Qwen proxy；
4. 分开记录 formal files accessed 与 formal cases scored；
5. P09 历史数字不进 P10 effect denominator；先重跑 sealed A0；
6. P10 继续保持 `X0_NOT_STARTED / execution_authorized=false`。

完整 reviewer trace：`.aris/traces/experiment-audit/2026-09-03_run01/`。
