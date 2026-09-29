# MiLAi Repository Map

## 当前布局

```text
MiLAi/
├── MiLAi-Product/            deployable product source of truth
├── MiLAi-Lab/                research/evaluation source of truth
├── MiLAi-Artifact-Archive/   historical index and preservation source of truth
├── .github/                  root composition and boundary CI only
├── README.md                 cross-repository navigation
├── SOURCE_OF_TRUTH.md        ownership and dependency policy
├── REPO_MAP.md               this map
├── AGENTS.md                 cross-repository contribution rules
└── LEGACY_READ_ONLY.md       retirement and recovery policy
```

## 目录归属

| 主题 | 当前入口 | 处理原则 |
| --- | --- | --- |
| HTTP/MCP/Runtime/DB/migrations | `MiLAi-Product/runtime`, `MiLAi-Product/integrations` | 只在 Product 修改；以产品测试、迁移和公开契约为准 |
| 产品架构、合同、示例、发布说明 | `MiLAi-Product/architecture`, `contracts`, `examples`, `docs` | 只保留产品视角；实验协议进入 Lab |
| benchmark、scorer、研究 adapter、prototype | `MiLAi-Lab/src`, `studies`, `configs`, `tests`, `docs` | Product-faithful arm 必须锁定公开 Product 身份 |
| 历史运行结果、legacy 快照、SHA 清单 | `MiLAi-Artifact-Archive/catalogs`, `manifests`, `preserved-user-work` | 只读证据；不作为 import 包或运行依赖 |
| 重组 inventory/diff/结果 | `MiLAi-Artifact-Archive/manifests/reorganization/v1.0` | 机器可读清单与人工差异决策的唯一归档位置 |
| Product application seams | `MiLAi-Product/runtime/src/milai/application/recollection`, `context_prepare` | facade、route、binding、serialization 等稳定边界；兼容入口保留在旧模块路径 |
| OpenWorker host seams | `MiLAi-Product/integrations/openworker-mcp/src/milai_openworker_mcp/host` | Host orchestrator 与 host 兼容层；memory/provider/tool 组件不得回流到根目录 |

## Lab 内部结构

| 目录 | 维护职责 |
|---|---|
| `MiLAi-Lab/src/milai_lab/application/` | 可复用业务 world、操作 journal、工具与恢复能力；不导入 runner |
| `MiLAi-Lab/src/milai_lab/runners/` | 实验阶段与运行资源编排，保留旧入口兼容 |
| `MiLAi-Lab/src/milai_lab/methods/` | 明确方法身份的记忆/工作视图实现 |
| `MiLAi-Lab/src/milai_lab/baselines/`、`providers/` | Agent/参考系统接口与实际模型协议 |
| `MiLAi-Lab/docs/`、`data/manifests/` | 协议、结果、来源身份与精简证据 |

详细入口见 [Lab 项目地图](MiLAi-Lab/docs/PROJECT_MAP.md)，
本轮整合见 [GitHub 合并记录](MiLAi-Lab/docs/GITHUB_MERGE_AND_STRUCTURE_20260929.md)。
上述是维护职责，不代表所有历史模块均已完成相同分层；实验状态以当前状态页为准。

## 运行与测试入口

- Product：先进入 `MiLAi-Product/`，按其 `pyproject.toml`、`uv.lock`、README 和 CI 执行。
- Lab：先进入 `MiLAi-Lab/`，按其 `pyproject.toml`、`uv.lock`、README 和 CI 执行。
- Archive：使用 `MiLAi-Artifact-Archive/tools/` 的确定性 build/validate 工具。
- 根目录 CI 只负责路径过滤、边界扫描和组合门禁；不复制子项目的业务测试实现。

## 不可恢复地删除前的证据链

```text
inventory（100% coverage）
→ divergence review（每个 diverged 有决定）
→ tests/package/boundary checks
→ annotated tag + clean commit
→ retire root legacy
→ final report + remote verification
```

重组前根目录内容可通过 `pre-codebase-reorg-v1` 和 inventory 中记录的 SHA 恢复。
最终交付索引见 `MILA_CODEBASE_REORGANIZATION_RESULTS_v1.0.md`。
