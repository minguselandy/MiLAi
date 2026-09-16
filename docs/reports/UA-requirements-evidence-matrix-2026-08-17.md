# UA-00～UA-08 Requirements-to-Evidence Matrix

> 审计日期：2026-08-17  
> 审计口径：以 `MiLAi_可用性与Agent接入设计开发文档_v1.md` 的显式交付、Gate、测试清单和
> Agent Integration Beta DoD 为准；“存在代码”不能替代范围匹配的运行证据。  
> 当前决定：candidate.2 `READY FOR INDEPENDENT RE-REVIEW`；candidate.1 的独立审查为
> `REVISE`，UA-F01～UA-F05 已整改但尚未由作者自行提升为 Beta。

## 工作流状态

| 工作流 | 关闭证据 | 判定 | 边界 |
|---|---|---|---|
| UA-00 | ADR-020/021/022、REST inventory、Agent v1 contract、tool threat model、compatibility policy、adapter dependency-boundary tests | PROVEN | 未引入 direct DB、review tool 或新 canonical semantics |
| UA-01 | 安全 init/doctor/status/start/stop、MANAGED/ADOPTED、隔离全链 smoke、first-run/rotation runbook | PROVEN | Developer Ready；默认 loopback/SYNTHETIC_ONLY |
| UA-02 | capabilities、OpenAPI/tool contract、typed async/sync SDK、Envelope、typed errors、retry/idempotency、generic tools、build/install | PROVEN | SDK 不依赖 Runtime DB/schema；`AgentRecallPolicy` 固定 Scope/authority/consistency/limit |
| UA-03 | 三档 capture policy、lifecycle hooks、Evidence/Proposal 分离、严格 ProposalDraft、Episode refs、pending inbox、replay/idempotency tests | PROVEN | model output 不成 Evidence；Agent 不可 review；stale head 在 proposal POST 前拒绝 |
| UA-04 | official MCP v2 stdio、三 profile、两协议、官方 host + 独立 wire host、重连与 substitution negatives | PROVEN | remote disabled；review/direct mutation/bulk delete 不可发现 |
| UA-05 | generic loop、LangGraph、AutoGen、coding hook、四份可执行示例、同一三会话 fixture | PROVEN | checkpoint 与 MiLAi state 分离；framework state/kwargs 不可扩大 host policy；单可信 orchestrator |
| UA-06 | ONNX provider、0027 identity、13-case quality gate、outage fallback、目标设备延迟/吞吐/失败/成本 | PROVEN | optional local provider；不是 SLA，不授权外部 embedding |
| UA-07 | AEAD、rotation、wrong-key/tamper、encrypted restore、server data-mode gate、三类 import dry-run、privacy review | IMPLEMENTATION PROVEN | `NO-GO FOR LOCAL PRIVATE BETA`：缺用户批准和环境级独立恢复接受 |
| UA-08 | 六包 versioned artifacts、六 fresh-venv install、三会话 E2E、archive-aware package scan、security/perf reports、known limitations、current-byte inventory builder | CANDIDATE.2 | P0 泄露制品已删除且全凭据/KEK 已轮换；等待独立 re-review；不得宣称 Schema frozen/Production |

## Agent Integration Beta DoD

| # | 要求 | 关闭证据 | 判定 |
|---:|---|---|---|
| 1 | clean checkout 可重复启动/诊断 | UA-01 clean managed profile；doctor 17 PASS；隔离 smoke 自动建库/清理 | PROVEN |
| 2 | SDK/MCP 获取 Gate 记忆/OpenIssue | 三会话 E2E 的 Session 1/2；rejected candidates 的 issue ID 保真 | PROVEN |
| 3 | abstention/degraded/trace 保真 | typed envelopes、contract tests、generic/MCP/LangGraph 独立 trace | PROVEN |
| 4 | capture/propose，不能 self-review | server scopes、tool catalogs、lifecycle tests、独立 reviewer API path | PROVEN |
| 5 | retry 无重复副作用 | 429/503 same bytes/key、409 no retry、hook replay、Runtime idempotency | PROVEN |
| 6 | model output 不成 Evidence/Claim | `after_model` no-op、deny sources、contract/lifecycle negatives | PROVEN |
| 7 | credential/正文不入日志/context/package | secret-free config、bounded data-only formatter、allowlisted sdist、recursive archive scan、credential/KEK rotation、Blob plaintext scan | PROVEN |
| 8 | revoke 后所有 adapter fail closed | Session 3：generic/MCP/LangGraph 均 `GROUNDING_BLOCKED`，随后 purge/erasure | PROVEN |
| 9 | generic + MCP + native E2E | 三会话 machine report；SDK、两 MCP hosts、LangGraph，附 AutoGen read | PROVEN |
| 10 | 外部项目非启动依赖/authority | import-boundary scan/tests、Runtime lock、外部项目只作 benchmark/reference | PROVEN |
| 11 | 完整 source/contract/test/package inventory | `build_ua_inventory.py` 覆盖 root Git/CI、Docker role bootstrap、integration/runtime/config/artifact bytes；missing/cache/symlink negatives；独立复算待 review | PROVEN BY CONSTRUCTION / REVIEW PENDING |
| 12 | experimental/candidate banner | capabilities、health、UI、README、runbook、known limitations | PROVEN |
| 13 | real data 只在 SG-01 后 | PERSONAL 在 SYNTHETIC_ONLY 下 server-side 403；当前配置与报告仍 DENIED | PROVEN |
| 14 | 独立 reviewer 无 P0/P1 | candidate.1 review=`REVISE`；candidate.2 已提交精确整改证据，等待新 re-review | PENDING |

## 当前可发布声明

独立 review 结束前，只允许描述为：

```text
Agent Integration: 0.1 RELEASE CANDIDATE / synthetic or de-identified
Schema: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
Implementation: CANDIDATE
Real personal data: DENIED
Remote/multi-agent governance: NOT ENABLED
```

若独立 reviewer 无开放 P0/P1，才可把第一行提升为 `0.1 BETA`；UA-07 的 Local Private Beta
仍独立保持 NO-GO。
