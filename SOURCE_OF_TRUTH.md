# MiLAi Source of Truth

本文件是 MiLAi 单仓库的跨目录治理规则。它解决“同一份实现有多个副本”时应当相信哪里，
不改变 Runtime、数据库 Schema、公开 API、检索语义或实验结论。

## 唯一权威边界

| 目录 | 唯一职责 | 可以作为权威的内容 | 明确不是 |
| --- | --- | --- | --- |
| `MiLAi-Product/` | 可部署产品 | Runtime、迁移、公开契约、客户端、MCP、OpenWorker/Host 适配器、产品测试与发布文档 | benchmark 数据、研究 scorer、实验候选、历史 Goal/运行产物 |
| `MiLAi-Lab/` | 研究与评测 | 研究基础设施、实验协议、配置、适配器、分析、scorer、prototype、simulation、结果 | Product 私有实现、canonical 写入、产品发布实现 |
| `MiLAi-Artifact-Archive/` | 历史证据与索引 | 历史文件的清单、SHA-256、快照索引、可追溯元数据与恢复说明 | 可导入运行时、活动产品代码、活动 Lab API |
| 根目录 | 跨仓库导航与治理 | 本文件、`REPO_MAP.md`、`AGENTS.md`、`README.md`、贡献/安全规则、CI 入口 | 任何产品/研究实现、测试、脚本、实验报告的第二份副本 |

## 依赖方向

```text
MiLAi-Product  <-  MiLAi-Lab（仅公开 MCP/client/contract/testkit 与锁定身份）
MiLAi-Artifact-Archive  <-  Product/Lab 的显式 provenance manifest（不执行运行时）
根目录导航/CI  ->  Product、Lab、Archive
```

- Product 不得导入 Lab、根历史目录或 Archive 的运行时代码。
- Lab 不得导入 Product 私有模块；Product-faithful 实验必须通过公开接口或发布的 testkit，
  并记录 `product.lock.json` 或等价身份。
- Archive 的 Python 工具只能读取输入并生成索引，不能成为 Product/Lab 的 import 依赖。
- 允许跨边界传递版本、commit、manifest、SHA-256 等 provenance；不允许以复制源码的方式
  形成第二个活动实现。

## 根目录历史内容的处理

重组前根目录的 `architecture/`、`contracts/`、`docs/`、`evals/`、`examples/`、
`integrations/`、`research/`、`runtime/`、`scripts/`、`tests/` 以及根级历史 Goal/报告，
均视为 legacy input。它们不再定义当前实现，也不自动向 Product/Lab 回流。

每一份 legacy 文件必须在重组清单中有 owner、分类、对应路径、SHA-256、动作和审查记录。
只有经过语义 diff、明确 owner 决定和测试验证的最小变更，才能另开 forward-port 行为 PR；
禁止把整个 legacy 根目录 bulk merge 到 Product 或 Lab。

Git tag、Git history 和 Archive manifest 是恢复手段；重复的活动源码不是备份策略。

## 变更纪律

本仓库的重组 PR 只做结构和治理变更，不调 retrieval score/rank/threshold/budget，不改
Evidence/Canonical 语义，不重写 migration，不消耗 formal holdout，也不把实验结论升级为产品结论。
如发现必须改行为才能通过验证，记录到 `MiLAi-Product/docs/TECH_DEBT.md`，另开行为变更 Goal。

重组回滚点：`pre-codebase-reorg-v1`。完成状态以
`MILA_CODEBASE_REORGANIZATION_RESULTS_v1.0.md` 为最终交付索引。
