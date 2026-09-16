# MiLAi

MiLAi 是一个受治理的个人记忆系统单仓库。当前仓库已经收敛为三个有明确职责的
first-party bundle；根目录只提供跨仓库导航、边界规则和 CI 入口。

## Source of Truth

- [`MiLAi-Product/`](MiLAi-Product/)：可部署产品唯一实现，包括 Runtime、PostgreSQL 迁移、
  公开契约、Python client、MCP、OpenWorker/Host 适配器、产品测试和发布文档。
- [`MiLAi-Lab/`](MiLAi-Lab/)：研究、评测、benchmark、scorer、prototype 和 simulation 唯一实现。
- [`MiLAi-Artifact-Archive/`](MiLAi-Artifact-Archive/)：历史文件、运行产物和 legacy 的索引、
  SHA-256 身份与恢复证据；不是可导入运行时。

详细规则见 [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) 和 [`REPO_MAP.md`](REPO_MAP.md)。
根目录 legacy 仅按 [`LEGACY_READ_ONLY.md`](LEGACY_READ_ONLY.md) 取证，并将在清单、差异审查和
回滚 tag 固定后退出活动面。

## 开发入口

```text
Product  → MiLAi-Product/README.md
Lab      → MiLAi-Lab/README.md
Archive  → MiLAi-Artifact-Archive/README.md
```

各 bundle 保留自己的 `pyproject.toml`、`uv.lock`、测试和运行说明。根仓库不提交第三方 clone、
虚拟环境、uv cache、模型/数据下载、日志、运行时状态、wheelhouse 或生成性大文件。

## 重组证据

重组的机器清单和 divergence review 归档在
`MiLAi-Artifact-Archive/manifests/reorganization/v1.0/`；完成报告为
`MILA_CODEBASE_REORGANIZATION_RESULTS_v1.0.md`。恢复点为 Git tag `pre-codebase-reorg-v1`。

当前产品仍是 `0.1.x CANDIDATE`，Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
