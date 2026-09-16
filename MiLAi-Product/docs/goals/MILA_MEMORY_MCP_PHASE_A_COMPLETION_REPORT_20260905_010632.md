---
document_id: MILA-MEMORY-MCP-PHASE-A-COMPLETION
version: "1.0"
status: PASS_MEMORY_MCP_FUNCTIONAL_BASELINE
date: 2026-09-05
milestone: PHASE_A_MEMORY_MCP_FUNCTIONAL_BASELINE
release_posture: CANDIDATE_NOT_PUBLIC_PRODUCTION_READY
---

# MiLA Memory MCP Phase A 完成报告

## 1. 结论

Phase A 已完成并通过：一个标准 MCP client/Codex 可以通过单一 Streamable HTTP endpoint，
在真实 credential binding、真实 PostgreSQL、真实 API 与 worker 上完成 MiLA 的读取、写入、
治理式修改、撤销/删除状态和非 Canonical Working State 生命周期。

```text
PASS_MEMORY_MCP_FUNCTIONAL_BASELINE
```

本结论证明的是功能基线，不表示当前明文公网 IP + 静态 Bearer 部署已达到公网生产安全要求。
生产发布仍需要 HTTPS，以及与发布策略匹配的认证/凭据交付方案。

## 2. 已实现范围

- `codex-full` 单 endpoint 注册 13 个按用户意图划分的工具；
- 标准 Streamable HTTP MCP `initialize`、`tools/list` 与结构化工具调用；
- `resolve/get` 读取 Evidence Context 与精确 Claim；
- `capture` 写入不可变 Evidence，不直接改 Canonical；
- `capture -> proposal -> review -> ClaimVersion` 治理式修改；
- `revoke -> immediate read exclusion -> deletion status` 删除闭环；
- `working_state get/update` 的 ABSENT、V1、V2、exact-head CAS 与跨进程恢复；
- mutation `operation_id` 按认证 principal、scope 与 tool 做内部命名空间隔离；
- Exact Claim、Proposal、Evidence、deletion、cleanup 以及 Proposal 内全部 Evidence refs 的
  bound-project 校验；
- 自动审计如实记录 `authorization_evidence=NOT_SERVER_VERIFIED` 与
  `confirmation_role=ACCIDENT_GUARD_ONLY`，不把 confirmation literal 伪装成用户授权证明；
- deployment-neutral 远程注册包与 Codex/通用客户端使用文档。

## 3. 真实 E2E 凭据

### 3.1 Disposable PostgreSQL lifecycle

执行 opt-in 真实 PostgreSQL 测试：

```text
MILAI_MCP_BASELINE_E2E=1 \
uv run pytest -q tests/test_codex_full_postgres_e2e.py

1 passed in 8.82s
```

测试使用独立 disposable database，迁移至 head，并启动真实 API、worker 与两个不同
project-bound MCP。覆盖：

```text
13-tool discovery
Working State ABSENT -> V1 -> V2 -> restart GET V2
stale CAS rejection
principal isolation
idempotent retry and operation conflict
capture -> resolve
Claim V1 -> SUPERSEDE -> APPROVE -> Claim V2
revoke -> resolve exclusion -> deletion status
cross-project Evidence grounding rejection with no Proposal residue
```

### 3.2 公网候选 endpoint

最终重启后，受控开发 endpoint `http://36.140.33.19:7968/mcp` 完成：

```text
initialize/tools-list
  -> authenticated=true
  -> tool_count=13
  -> catalog=codex-full-v1

capture -> resolve -> revoke -> deletion COMPLETED/ERASED
```

`/healthz` 与 `/readyz` 均返回成功。以下三个服务均为 `active + enabled`，最终检查的
`NRestarts=0`：

```text
milai-product-api-mcp.service
milai-product-worker-mcp.service
milai-codex-full-public.service
```

### 3.3 不加载 Skills 的 Codex 验证

使用隔离的空 `CODEX_HOME`，不加载 Skills 或 plugins，只注册远程 MiLA MCP。Codex 对测试
历史问题只进行一次 `milai_memory_resolve` 调用并正确回答 `6521`；测试 Evidence 随后完成
revoke 与物理清理。这证明结果不是额外 Skill prompt 触发的旁路行为。

## 4. 自动测试与构建

```text
MCP pytest                 125 passed, 1 skipped
Real PostgreSQL E2E        1 passed
Ruff                       PASS
mypy                       PASS (12 source files)
Python package build       PASS (0.1.4 sdist + wheel)
Runtime smoke test         PASS
Remote archive SHA-256     PASS
Remote embedded manifest   PASS
```

默认跳过的一个测试就是显式 opt-in 的真实 PostgreSQL E2E，已按上一节单独运行并通过。

远程包：

```text
integrations/mcp/dist/remote-client/milai-codex-remote-client-0.1.4.tar.gz
SHA-256 de291cf82aa31be6407c1e53115b1eec25962d71572f461378abb561737be328
```

## 5. Phase A Hard Invariants

| 不变量 | 结果 | 证据摘要 |
| --- | --- | --- |
| Scope 不串联或泄漏 | PASS | 两 project 真实 E2E、principal Working State 隔离、nested Evidence refs 负测 |
| Recall/Working State 不直接改 Canonical | PASS | `canonical_changed=false`；Canonical 仅经 Proposal/Review |
| Working State exact-head CAS | PASS | V1/V2 与 stale version conflict |
| Mutation 幂等、同 operation 异 payload冲突 | PASS | unit/HTTP/真实 PostgreSQL E2E；principal/tool/scope namespacing |
| Revoked Evidence 不返回或参与有效 grounding | PASS | revoke 后 resolve exclusion 与 deletion completion |
| Payload 只是 data，不是 scope/authority/authorization | PASS | server-owned binding；审计明确未验证当前用户授权 |

Namespace cleanup 只验证工具、scope、confirmation 与状态合同；本基线没有在真实用户 namespace
上执行清理。合成 Evidence 的 revoke/物理删除仅作用于本次测试创建的精确对象。

## 6. Subagent Boundary Review

| Reviewer | Decision | Required fixes |
| --- | --- | --- |
| Functional | PASS | 0 |
| Architecture | PASS | 0 |
| Generalization/Simplicity | PASS | 0 |

Architecture reviewer 最初发现 Proposal 的 nested Evidence refs 未做 project 绑定校验，以及
审计把 confirmation 写成授权证明。实现已修复并补充 CREATE、SUPERSEDE、mixed refs 单元负测
及双 project 真实 PostgreSQL E2E；复审结果为 PASS。

## 7. 失败反思与修复

开发中遇到的失败均先归因再修复，没有通过放宽断言掩盖：

- 系统 Python 环境不匹配：改用项目锁定的 virtual environment；
- 撤销参数示例与 Runtime 枚举漂移：把 revoke/cleanup `reason_code` 固定为精确枚举并修正文档；
- API/worker 使用相对 Blob root 导致工作目录漂移：改为同一绝对 root，按 exact referenced blob
  恢复缺失对象，并通过受支持的 dead-letter retry 恢复 delivery；
- 公网 IP 经本机代理返回假 `502`：直连验证服务正常，只为该 IP 增加窄 `NO_PROXY`；
- 远程包内层清单首次验证使用了错误工作目录：按压缩包实际根目录重新校验，全部文件通过；
- 子代理发现 nested Evidence project 边界缺口：在 mutation 前全量校验 supporting/contradicting
  refs，并验证失败时 Runtime 不收到任何 Proposal 写入。

## 8. 已知限制与延后项

- 公网候选 endpoint 是明文 HTTP + 静态 Bearer，只用于当前受控开发验证；
- URL-only OAuth/DCR 公网 onboarding 尚未完成 HTTPS 实际部署；
- 真实 PostgreSQL E2E 当前为 opt-in，后续可增加显式 CI job；
- readiness 目前主要证明 MCP/API 可用，后续可纳入 worker/projection 健康；
- `milai_proposals_list` 当前先做 tenant-wide bounded fetch 再按 project 过滤；高数量多项目场景
  可在出现真实分页问题时下推 project filter；
- 本次不实现 Event journal、reconciliation、自然 Working State adoption 或 Product-11 效果 claim。

这些限制不阻塞 Functional Baseline，但阻止将当前候选部署标记为公网生产就绪。

## 9. 下一里程碑

下一步进入 Phase B — Host Continuity，保持增量范围：

```text
stable TASK binding
  -> deterministic session-start working_state_get
  -> bounded non-canonical bootstrap
  -> real resume usability
```

Phase B 不新增 Event journal，不要求自动 checkpoint，也不消费 Product-11 Formal holdout。只有
真实 resume 证明 Working State 有产品价值后，才进入 Phase C Minimal Event Reconciliation。
