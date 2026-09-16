# MILA-PRODUCT-08：读取链路一致性修复

状态：`IMPLEMENTED / OPENED R3 NOT YET EXECUTED`  
日期：`2026-09-03`  
用途：Context-only engineering diagnosis；不调用 Answer、Judge 或 formal holdout

## 假设

Product-07 的主要损失发生在 RecallWorkspace 之前：全局 FTS 候选被严格 Binding/EvidenceSet
边界清空，且 Dense 没有执行。若候选池被冻结，则只放宽 informational Reader admission 的 X
应满足 `ReaderVisible(C) ⊆ ReaderVisible(X)`；在 X 基础上加入真实 additive FTS+Dense 的 Y 应
提高完整 EvidenceSet 与 group coverage，而不丢失 A 已完整或已命中 gold session 的 case。

## 固定四臂

| Arm | Kind | 定义 |
| --- | --- | --- |
| A | `PRODUCT_BLACK_BOX` | 当前 direct 连续性参照 |
| C | `PRODUCT_TESTKIT` | frozen global-query FTS + legacy strict admission |
| X | `PRODUCT_TESTKIT` | 与 C 完全相同 candidate/Decision snapshot + informational soft admission |
| Y | `PRODUCT_TESTKIT` | frozen full-query FTS backbone + requirement-local FTS + real Dense + soft admission |

C/X/Y 每个 case 只建立一次进程内 frozen acquisition snapshot。重放阶段 repository、embedding、
vector、Provider 和 Canonical mutation 调用都必须为 0；报告只保存 Evidence/source-turn identity 与
digest，不保存 Raw Evidence 正文。RecallWorkspace 固定关闭。

Product pin：`data/locks/product08-product.lock.json`，包含独立发布的
`context-testkit-v0.1` interface。执行器：`tools/run_product08_context_repair.py`。

## Context gate

24 个 opened R3 case 必须同时满足：

```text
C/X before-boundary identity match        24/24
C/X DecisionSnapshot match                24/24
ReaderVisible(C) subset ReaderVisible(X)  24/24
nonempty candidates -> zero Context        0 cases (X and Y)
real Dense disposition EXECUTED           24/24
Y complete EvidenceSet gain vs A          >= 4
Y mean group coverage gain vs A           >= 0.10
Y recovered capability shapes             >= 3
A complete / any-gold case losses           0 / 0
tenant leak / Canonical mutation            0 / 0
```

只有该 gate 通过，才可另行申请 Reader/Answer 验证。此实现不自动切换默认值，也不授权 500-case
formal holdout。

## 执行前提与当前结论

执行必须显式提供冻结的真实 embedding provider、model path、model ID 与 source dimensions；
projection 固定为 128d。deterministic hash 或 Dense disposition 缺失均不能作为 Y 的执行证据。

截至本文日期，代码、Testkit contract、pin、Lab gate 单元测试和离线仓库质量门槛已实现；真实模型
路径尚未提供，因此 24-case opened R3 未执行，不能声称 H1 通过。两个 Product-08 feature flags
保持默认关闭，Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
