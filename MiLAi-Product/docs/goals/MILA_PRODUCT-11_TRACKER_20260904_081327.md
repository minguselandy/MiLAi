---
document_id: MILA-PRODUCT-11-TRACKER
version: "0.2"
status: X0_ACTIVE_HUMAN_ADJUDICATION_REQUIRED
created_at: "2026-09-04T08:02:14+08:00"
amended_at: "2026-09-04T08:13:27+08:00"
goal: MILA-PRODUCT-11@0.3
adr: ADR-032
acceptance_contract: MILA_PRODUCT-11_ACCEPTANCE_CONTRACT@0.1
execution_authorized: true
formal_holdout_authorized: false
---

# Product-11 执行 Tracker

## 当前结论

用户已授权执行完整 Goal，但阶段门不变。当前只进入 X0；仓库没有满足 Product-11 要求的
24-case、双人人工确认 seal。Product-10 label 是 `model_assisted_proxy/PENDING`，不能升级为 gold；
Formal 500 不得读取。

```text
current block                 X0
current status                X0_ACTIVE_HUMAN_ADJUDICATION_REQUIRED
Product behavior              NOT_STARTED
database migration            NOT_STARTED
effect run                    NOT_STARTED
formal files accessed P11     false
formal cases scored P11       0
```

## Gate tracker

| Block | Required evidence | Status | Exit |
| --- | --- | --- | --- |
| X0-A | Goal v0.3 authorization receipt | COMPLETE | authorization recorded |
| X0-B | ADR-032 accepted | COMPLETE | implementation gated by X0 |
| X0-C | acceptance contract frozen | COMPLETE | scorer/runtime/DB gates frozen |
| X0-D | new non-Formal 24-case candidate slice | COMPLETE | 24 cases / 94 turn refs / intended strata 8+8+8 |
| X0-E | real human annotator complete | BLOCKED HUMAN | 0/24 signed |
| X0-F | independent human reviewer complete | BLOCKED HUMAN | 0/24 signed, identity must differ |
| X0-G | adjudication + overlap/capability/opportunity seal | NOT ENTERED | `PASS_PRODUCT11_X0_HUMAN_SEAL` |
| X1 | persisted-frontier continuation effect | BLOCKED BY X0 | C1 PASS/FAIL |
| X2 | explicit intra-source SHADOW effect | BLOCKED BY X0 | C2 PASS/FAIL |
| X3 | frontier/renderer integration | NOT ELIGIBLE | requires X1 PASS + X2 PASS |
| X4 | real Codex attribution | NOT ELIGIBLE | requires memory-complete preseal |

## 已冻结工程决定

- A1 primary：same query，global reacquisition/pool extension/replanning 为 0；只接受
  `PERSISTED_FRONTIER`。
- A1R：residual query 与 `RESIDUAL_ACQUISITION` 只作 secondary diagnostic。
- successor：数据库唯一 operation fingerprint；request ID 仅 trace。
- assertion：`FRONTIER_EXHAUSTED` 仅陈述当前 query lineage 已执行 route exhaustion。
- X2：fine acquisition 先 SHADOW；hydration 不计 discovery。
- X3：两项 claim 都 PASS 且最小 X2 variant sealed 才进入。
- 资源：120 frontier refs、generation 4、successors 8、root states 16、state 256 KiB。
- 模型路径：Reader/vLLM/semantic retry 均为 0。

## 下一动作

1. 由真实 annotator 使用 `product11-annotator.packet.v0.1.json` 独立提交 24 case；
2. 由不同的真实 reviewer 使用 `product11-reviewer.packet.v0.1.json` 独立提交 24 case；
3. 人工解决分歧并填写 `product11-human-adjudication.template.v0.1.jsonl`；
4. 运行 seal validator 和 frozen A0 opportunity audit；
5. 仅在 X0 PASS 后生成 Product behavior tree/lock，开始 X1 implementation。

## X0 preparation receipt

```text
run_id                         p11-x0-prep-20260904a
source fixture SHA-256         35a7947eb523b718abbd1e81fff3f390ca4f03db371b25f97999a3d90157f537
candidate label SHA-256        647374902e8bb34405f93133a7cda49744e9c91252ef8ec708b4c497d8aa5c0b
case / turn refs               24 / 94
intended strata                continuation 8 / intra-source 8 / control 8
minimum capability count       6
human COMPLETE                 0 / 24
formal files/cases             false / 0
seal negative test             PASS; PENDING/model template rejected
```

## 停止条件

在 X0-G 前不得：

```text
新增 Product behavior
新增 migration 0050
运行 X1/X2 treatment
运行真实 Codex
读取或计分 Formal 500
```

AI 生成的 candidate/proposal 永远保留 `human_adjudication_status=PENDING`，不能自行签署为
`COMPLETE`。
