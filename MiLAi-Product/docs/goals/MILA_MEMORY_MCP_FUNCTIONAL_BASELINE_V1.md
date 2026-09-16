---
document_id: MILA-MEMORY-MCP-FUNCTIONAL-BASELINE-V1
version: "1.0"
status: FROZEN_ENGINEERING_BASELINE
frozen_at: "2026-09-05T09:33:00+08:00"
product_version: 0.1.0-candidate
product_tree_sha256: f998c2d96c6ae4a4e2ffa246d12257938af29a9e49c60f48ad21e7b50250cad1
mcp_interface_sha256: aee9e4014ebaf502166d91618a76bcf7a277d4a940d612e5f689d1b88d55f650
repository_base_commit: 1b5e4a7122da2b38b9a57bba143215cc0afa3387
formal_holdout_consumed: false
---

# MiLA Memory MCP Functional Baseline V1

## 1. 基线定义

`MILA_MEMORY_MCP_FUNCTIONAL_BASELINE_V1` 是当前 MiLA 可持续真实使用的工程基线：

```text
Codex
  -> authenticated Streamable HTTP MCP
  -> MiLA Runtime
  -> PostgreSQL / Evidence / Canonical governance / Host state
```

权威源码身份是 `product.manifest.json` 的 `product_tree_sha256`，而不是上面的
`repository_base_commit`。后者只是共享工作树的 Git 基础提交；当前工作树包含用户已有和本轮的
未提交变更，因此本次没有擅自创建 commit、tag 或覆盖用户版本历史。

## 2. 已成立的工程能力

```text
Memory MCP Functional Baseline        PASS
HTTP authenticated lifecycle          PASS
Evidence resolve/get                   PASS
Evidence capture                       PASS
Proposal/review Claim versioning       PASS
Evidence revoke/deletion status        PASS
Working State get/update + CAS         PASS
Host-managed session continuity        PASS
Event-grounded reconciliation          PASS
Persisted-frontier continuation        PASS
Explicit intra-source acquisition      SHADOW
Canonical/scope/authority boundaries   PRESERVED
```

Codex 可以通过一个 MCP endpoint 完成 recall、capture、governed update、revoke、Working State、
跨 Session 恢复与显式 reconciliation。Memory content 和 Working State 始终是 data，不是
instruction 或 mutation authorization。

## 3. 部署基线

```text
public endpoint                         http://36.140.33.19:7968/mcp
MCP protocol                            Streamable HTTP / 2025-06-18
profile                                 codex-full
tool catalog                            13
Alembic head                            0054_intra_source_shadow
retrieval continuation                 enabled
intra-source acquisition               SHADOW
API / worker / public MCP               active
```

公网 MCP 保持认证要求；无凭证连接返回 401，不以降低认证换取易用性。

## 4. 验证基线

```text
Runtime non-integration                 805 passed
fresh PostgreSQL integration            137 passed, 2 existing dependency skips
MCP                                     155 passed, 1 skipped
Python client                           175 passed
Ruff / mypy / package builds            PASS
Functional subagent review              PASS
Architecture subagent review            PASS
Generalization/Simplicity review         PASS
```

## 5. 明确不声明

```text
Product-11 Research X0 seal             NOT COMPLETE
D2 product effect                       UNKNOWN
Dense fine acquisition                  NOT NEEDED
Fine acquisition -> frontier            NOT AUTHORIZED
Anchor-first renderer treatment         NOT ENTERED
Formal 500                              UNCONSUMED
```

D2 SHADOW 只证明 governed candidate acquisition 能运行；它没有证明 coverage gain、latency tradeoff
或进入公开 Context/frontier 的价值。

## 6. Failure-driven change admission

本基线之后默认不新增机制。新产品 Goal 必须至少满足一项：

1. 引用 `MILA_PRODUCTION_FAILURE_LEDGER.md` 中可复现的真实 failure ID；
2. 修复已证明的安全、scope、authority、durability 或兼容性缺陷；
3. Product-11 Research X0 已真实完成，需执行预注册 effect experiment；
4. 明确的依赖/EOL/部署故障迫使维护性变更。

仅有架构完整性、未来可能性或 synthetic interface completeness，不足以开启新机制开发。

## 7. D2 合法推进条件

D2 保持 `SHADOW`。只有以下条件之一成立才继续：

- 真实任务复现：coarse source 已命中，但 required turn/span 未进入 Host-visible cumulative Context；
- Product-11 X0 seal 完成并进入 X2 Research effect run。

在此之前不得启用 `FRONTIER`，不得添加 Dense，也不得扩大 first-call Context。

