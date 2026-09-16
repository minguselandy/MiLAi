---
document_id: MILA-PRODUCT-11-TRACKER
version: "1.3"
status: D1_D2_ENGINEERING_PASS_RESEARCH_X0_PARKED_SUBAGENT_OPPORTUNITY_INSUFFICIENT
created_at: "2026-09-04T08:02:14+08:00"
amended_at: "2026-09-05T12:31:30+08:00"
goal: MILA-PRODUCT-11@1.3
adr: ADR-032
acceptance_contract: MILA_PRODUCT-11_ACCEPTANCE_CONTRACT@0.1
execution_authorized: true
formal_holdout_authorized: false
engineering_mode_authorized: true
research_effect_claim_authorized: false
---

# Product-11 执行 Tracker

## v1.0 Engineering Mode 进展

后续用户授权已把普通产品开发与研究 claim 分离；旧 X0 block 只继续阻塞量化效果声明，不再阻塞
默认关闭的最小 persisted-frontier continuation。

```text
D1 Product behavior              PASS ENGINEERING BASELINE
database migration               0052 + 0053_continuation_hardening
public MCP input                 UNCHANGED
first-call selection             UNCHANGED
same-query continuation          PERSISTED_FRONTIER ONLY
global reacquisition Call 2      0
candidate-pool extension Call 2  0
query replanning Call 2          0
adjacent hydration Call 2        0
focused tests                    PASS
full Runtime unit+contract       793 PASS
fresh PostgreSQL integration     115 PASS / 1 dependency SKIP
MCP / Python-client tests        155 PASS / 1 SKIP / 175 PASS
live deployment                  0053 HEAD / API+MCP ACTIVE
real Streamable HTTP             55-Evidence two-page PASS
edge-principal state isolation  PASS
Formal files/cases               false / 0
P11-C1 quantitative effect       NOT CLAIMED
P11-C2 fine acquisition          D2 SHADOW ENGINEERING PASS / EFFECT NOT CLAIMED
```

实现文件包括 Runtime continuation service/repository、migration 0052/0053、`MemoryResolveService`
编排和 feature flag `MILAI_RETRIEVAL_CONTINUATION_V0_1_ENABLED`。研究 X0 记录继续保留在下文，不能
因工程功能通过而改写为 human seal PASS。完成凭据见
`MILA_PRODUCT-11_PHASE_D1_CONTINUATION_COMPLETION_REPORT_20260905.md`。

D2 Engineering 结果：

```text
mode                              lexical-only SHADOW
database migration                0054_intra_source_shadow
source boundary                   exact coarse Evidence -> DB-attested source_type/session
fine bounds                       50 source/session, 8 hits/source, 120 total
public MemoryContext/frontier      UNCHANGED
global source acquisition          0
Dense / Reader / vLLM              0 / 0 / 0
full Runtime                       805 PASS
fresh PostgreSQL integration       137 PASS / 2 existing dependency SKIP
MCP / Python client                155 PASS / 1 SKIP / 175 PASS
live deployment                    0054 HEAD / SHADOW / API+worker+MCP ACTIVE
subagent boundary reviews          3 PASS / required fixes 0
P11-C2 quantitative effect         NOT CLAIMED / BLOCKED X0
```

完成凭据见
`MILA_PRODUCT-11_PHASE_D2_INTRA_SOURCE_SHADOW_COMPLETION_REPORT_20260905.md`。

## Research Mode 历史结论

用户已授权执行完整 Goal，但阶段门不变。X0 source-only A0 已运行并通过操作门；随后才加载的
PENDING proxy join 为 `continuation 0 / intra-source 8 / control 16`，continuation 低于 8。
同时仍没有双人人工 seal。Formal 500 不得读取。

```text
engineering block             D1 PASS / D2 SHADOW PASS
research block                X0
research status               X0_PARKED_SUBAGENT_OPPORTUNITY_INSUFFICIENT
execution disposition         ENGINEERING_BASELINE_RETAINED / RESEARCH TERMINAL FOR SLICE
Product behavior              D1 + D2 SHADOW IMPLEMENTED / EFFECT UNCLAIMED
database migration            0052/0053/0054 IMPLEMENTED / EXPERIMENTAL
effect run                    NOT_STARTED
baseline read-only MCP        COMPLETE / retained as agent-memory
codex-full HTTP MCP           COMPLETE / 74 tests + clean install PASS
codex-full governance         SINGLE_HOST_FULL_CONTROL / independent review false
P11 continuation semantics    ENGINEERING E2E PASS / RESEARCH EFFECT BLOCKED X0
formal files accessed P11     false
formal cases scored P11       0
```

## v1.2 Subagent-sealed X0 terminal

用户明确授权以 subagent 取代人工审查后，两个 role-specific subagent 分别完成了
24/24 source-only case，其 60 个规范化 instance group 和 70 个 exact acceptable turn ref
完全一致。该路径使用独立 `SUBAGENT_SEALED` schema，不修改 HUMAN validator/template，
`human_adjudication_status=NOT_PERFORMED`。

frozen A0 机会派生结果为 `continuation=0 / intra-source=8 / control=16`，因此未达
`8/8/8` X0 门。Research 终态是
`PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY`；X1--X4 全部为
`NOT_ENTERED_BY_X0`，Formal access/scoring 仍为 `false/0`。原外部 HUMAN 路径作为历史可选分支
保留，不会被模型判断伪装成已完成。

最终 `20260905c` 链使用专用 source-only packet、执行前 immutable orchestration manifest、
两个全新 subagent invocation，以及 seal-time proposal 重算。架构复审结论为 `PASS`、required
fixes 为空。v0.2 receipt append-only supersede 早期证据链不完整的 `20260905a` receipt；旧文件
仍完整保留，`20260905b` 只有未使用 manifest。

## Gate tracker

| Block | Required evidence | Status | Exit |
| --- | --- | --- | --- |
| X0-A | Goal v0.3 authorization receipt | COMPLETE | authorization recorded |
| X0-B | ADR-032 accepted | COMPLETE | Research effect claim gated by X0 |
| X0-C | acceptance contract frozen | COMPLETE | scorer/runtime/DB gates frozen |
| X0-D | final non-Formal 24-case candidate slice | COMPLETE | 24 cases / 238 turn refs; all replacements preserved |
| X0-D1 | frozen label-blind A0 trace | COMPLETE | 24/24; fresh DB; cleanup; label/Formal 0 |
| X0-D2 | post-trace proxy opportunity audit | FAIL DIAGNOSTIC | 0 continuation / 8 intra / 16 control |
| X0-D3 | proposal-free dual-human workflow | READY | source-only templates; exact merge; conflicts emit no gold |
| X0-E | real human annotator complete | BLOCKED HUMAN | 0/24 signed |
| X0-F | independent human reviewer complete | BLOCKED HUMAN | 0/24 signed, identity must differ |
| X0-G | adjudication + overlap/capability/opportunity seal | NOT ENTERED | `PASS_PRODUCT11_X0_HUMAN_SEAL` |
| X0-SA | user-authorized independent subagent seal | COMPLETE / TERMINAL INSUFFICIENT | verified-chain `20260905c`; 24/24 exact agreement; 0/8/16 opportunities; architecture review PASS |
| X1 | persisted-frontier continuation effect | NOT ENTERED BY X0 | 0 continuation opportunities |
| X2 | explicit intra-source SHADOW effect | NOT ENTERED BY X0 | aggregate X0 gate failed; D2 remains Engineering SHADOW |
| X3 | frontier/renderer integration | NOT ELIGIBLE | requires X1 PASS + X2 PASS |
| X4 | real Codex attribution | NOT ELIGIBLE | requires memory-complete preseal |

## 已冻结工程决定

- A1 primary：same query，global reacquisition/pool extension/replanning 为 0；只接受
  `PERSISTED_FRONTIER`。
- A1R：residual query 与 `RESIDUAL_ACQUISITION` 只作 secondary diagnostic。
- successor：数据库唯一 operation fingerprint；request ID 仅 trace。
- assertion：只有持久化 official route-exhaustion receipt 才能使用 `FRONTIER_EXHAUSTED`；D1
  candidate-only state 使用 `PERSISTED_FRONTIER_EXHAUSTED` 或 `FRONTIER_ELIGIBILITY_CHANGED`。
- X2：fine acquisition 先 SHADOW；hydration 不计 discovery。
- X3：两项 claim 都 PASS 且最小 X2 variant sealed 才进入。
- 资源：120 frontier refs、generation 4、successors 8、root states 16、state 256 KiB。
- 模型路径：Reader/vLLM/semantic retry 均为 0。

## Research Mode 恢复动作（非当前工程阻塞）

1. 真实 annotator 复制并完成 `product11-annotator.submission-template.v0.1.jsonl` 的 24 case；
2. 不同真实 reviewer 独立完成 `product11-reviewer.submission-template.v0.1.jsonl`；
3. 运行 exact-agreement merger；有分歧只输出 conflict report，人工重新协调；
4. 若人工确认 continuation opportunity <8，按 Goal 进入 insufficient-opportunity terminal；
5. 只有人类 seal 实际达到 8/8/8 才能生成 Product behavior tree/lock。

## X0 preparation receipt

```text
run_id                         p11-x0-prep-20260904g
source file SHA-256            c1fee1f4e9f68e7d9a0b082984c4ed5e4952e1e3f72ae009afd264640ba4c709
source semantic SHA-256        6c9ab9560b87edf106c0524927043237c794cabd31c0d12050142befa7c65d66
candidate file SHA-256         8a510bd32d3dd2e8ad75cae624eb102a4b01ada93ab9c11db2270ab4674ffcba
case / turn refs               24 / 238
intended strata                continuation 8 / intra-source 8 / control 8
minimum capability count       6
human COMPLETE                 0 / 24
formal files/cases             false / 0
seal negative test             PASS; PENDING/model template rejected
```

最终 A0 `p11-x0-a0-20260904f` 的 redacted trace SHA 为
`eef498d36c35b102ca6943469c7b203113237b1bf63c3cb17cd8c95f9dd27a95`。proxy audit
`p11-x0-proxy-audit-20260904a` 的 case-view SHA 为
`5300bacc9d3a39149a12641353c181b0ee23095f3e64255e39790c46b5c7108c`。全部失败/替代关系见 Lab
append-only failure ledger；没有运行 treatment 或读取 Formal。

人工工作流收据为 `p11-x0-human-workflow-20260904a`：两份 submission template 均不含 model
proposal，source review view 不含 Product output，opportunity 字段由 frozen A0 trace 在人工一致后
推导。当前真实 human COMPLETE 仍为 `0/24`。验证明细见
`MILA_PRODUCT-11_HUMAN_WORKFLOW_AUDIT_20260904_091103.md`。

连续三次检查均未发现真实 submission，执行阻塞收据为 Lab
`var/product11/p11-execution-blocked-human-20260904a/summary.json`。这是可恢复的外部阻塞，不是
实验终态；恢复时不得重建 A0。

## 停止条件

在 X0-G 前，Research Mode 不得：

```text
运行 X1/X2 treatment
读取或计分 Formal 500
```

Engineering Mode 可以实现默认关闭、公开协议不扩张且通过核心安全/E2E 回归的最小功能；不得把
该工程收据包装成 X1/X2 effect PASS。真实 Codex 若只用于功能可用性 E2E，可以运行，但不得读取
Formal 或计算预注册 coverage 指标。

AI 生成的 candidate/proposal 永远保留 `human_adjudication_status=PENDING`，不能自行签署为
`COMPLETE`。
