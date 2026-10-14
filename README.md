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
历史 legacy 的取证与恢复规则见 [`LEGACY_READ_ONLY.md`](LEGACY_READ_ONLY.md)，
当前活动布局以仓库地图和各 bundle 入口为准。

## 开发入口

```text
Product  → MiLAi-Product/README.md
Lab      → MiLAi-Lab/README.md
Archive  → MiLAi-Artifact-Archive/README.md
```

各 bundle 保留自己的 `pyproject.toml`、`uv.lock`、测试和运行说明。根仓库不提交第三方 clone、
虚拟环境、uv cache、模型/数据下载、日志、运行时状态、wheelhouse 或生成性大文件。

## 当前 Lab 开发

开发分支 `feat/lab-global-development-20261014`，实现起点 `f86fc5c3`，首批代码 `c33e325d`。
执行[全局开发规划](MiLAi-Lab/docs/MILAI_GLOBAL_DEVELOPMENT_PLAN_20261014.md)。
[开发记录与运行方式](MiLAi-Lab/docs/MILAI_GLOBAL_DEVELOPMENT_20261014.md)包含实际查询结果和成本。

新配置 `MiLAi-Lab/configs/milai-global-source-v1.json` 接通独立来源枚举和 Unicode 分词；
Benchmark 明确使用 S0。20 条同库查询已运行：10 条机制来源 Top-1 为 10/10，
一位已暴露开发用户的 32 会话、10 条查询 Top-1 为 9/10。这是来源召回结果，尚非答案质量。
下一项是 B 的自包含片段、预算内证据选择与必要补读，随后推进 C 和正常 Host 连续故事。
完整计划仍在执行；训练与 Product 适配按规划中的实际收益条件推进。

- [代码结构与项目地图](MiLAi-Lab/docs/PROJECT_MAP.md)
- [架构与依赖边界](MiLAi-Lab/docs/LAB_ARCHITECTURE.md)
- [当前状态](MiLAi-Lab/docs/LAB_CURRENT_STATUS.md)
- [上一轮真实实验报告](MiLAi-Lab/docs/MILAI_EVIDENCE_DEVELOPMENT_20261013.md)

## 重组证据

重组的机器清单和 divergence review 归档在
`MiLAi-Artifact-Archive/manifests/reorganization/v1.0/`；完成报告为
`MILA_CODEBASE_REORGANIZATION_RESULTS_v1.0.md`。恢复点为 Git tag `pre-codebase-reorg-v1`。

当前产品仍是 `0.1.x CANDIDATE`，Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
