# MiLAi Codebase Reorganization Results v1.0

状态：结构整理与 Git 交付已完成；行为性技术债不在本次重组中偷偷解决。

## 交付范围

当前仓库按以下唯一权威边界组织：

| 区域 | 交付内容 |
| --- | --- |
| `MiLAi-Product/` | 可部署 Runtime、迁移、公开合同、Python client、MCP、OpenWorker/Host 适配器、产品测试与文档 |
| `MiLAi-Lab/` | 研究、实验、评测、scorer、prototype 与结果；通过公开 Product 接口或锁定身份消费 Product |
| `MiLAi-Artifact-Archive/` | 历史证据、SHA、inventory、差异审查、保留材料与恢复说明；不作为运行时依赖 |
| 根目录 | 导航、边界规则、跨 bundle CI；不保留第二份活动实现 |

根目录历史实现目录已退休，不再作为活动代码提交：`runtime/`、`integrations/`、`contracts/`、
`architecture/`、`evals/`、`research/`、`scripts/`、`tests/`。原始恢复点为 annotated tag
`pre-codebase-reorg-v1`。

## Git 提交与远端

本次整理的关键提交均已推送到 `git@github.com:minguselandy/MiLAi.git` 的 `main`：

| Commit | 内容 |
| --- | --- |
| `844e22f` | 重组前治理文档与恢复点 |
| `ba78b4b` | 确定性 inventory 工具 |
| `82575f7` | 删除前 inventory 快照与差异审查 |
| `0ac6079` | 退休根目录 legacy 活动实现 |
| `025e88d` | 根目录边界与组合 CI |
| `7464539` | Archive 最终索引绑定 |
| `99cc0c0` | Product recollection facade 包化，旧导入路径兼容 |
| `6361c59` | Product context preparation 的 contract/route/binding/serialization 拆分 |
| `9b2f3a5` | OpenWorker host orchestrator 与 `host_adapter.py` 兼容 shim |

交付检查时远端 `main` 指向 `9b2f3a5f55f9fbed34c23372fb12380921593b1f`，即当前本地
`HEAD`；推送历史未重写。

## Inventory 与保留策略

- 删除前清单覆盖 6423 个 tracked path，其中 legacy 2206 个。
- `DIVERGED=144`、`IDENTICAL=2055`、`LEGACY_ONLY=7`、`UNKNOWN=0`，覆盖率 100%。
- 144 个 diverged 文件已按 canonical Product/Lab owner 审查，没有 bulk forward-port。
- 7 个 legacy-only 条目已分别归档、只保留 hash/manifest，或以原字节移入 Archive 的
  `preserved-user-work/reorganization/v1.0/legacy-only/`；没有把运行时备份密文重新放回 Product/Lab。
- Git tracked 文件中没有 `.venv`、`venv`、`__pycache__` 或 third-party clone 目录；本地 uv 环境和
  用户未追踪目录没有删除。

## 结构拆分证据

### Product

- `milai.application.recollection` 变为包，接口位于 `recollection/facade.py`，兼容旧导入路径。
- `context_preparation.py` 保留服务兼容入口；确定性职责拆到 `context_prepare/`：
  `contracts.py`、`route_policy.py`、`binding.py`、`serialization.py`。

### OpenWorker

- 3691 行 Host adapter 实现移到 `host/orchestrator.py`。
- `host_adapter.py` 作为兼容层，保留历史公开和私有测试符号，并转发 `python -m` 命令入口。
- 原有 `memory_facade.py`、`provider_execution.py`、`reader_session.py`、`completion_capture.py`、
  `evidence_use.py` 等职责保持独立，后续可在不改变 shim 的情况下继续细拆。

这三次拆分都是独立提交，便于按 PR 类型回滚；没有修改检索排序、阈值、预算、Evidence/Canonical
语义或数据库 migration。

## 已执行验证

| 检查 | 结果 |
| --- | --- |
| recollection facade、续接、源内采集 | 16 passed |
| context preparation、facade contract、memory need contract | 25 passed |
| OpenWorker host adapter + adapter | 77 passed |
| Product context 模块 ruff | pass |
| OpenWorker host 模块 ruff | pass |
| boundary scanner | `PASS`, findings=0, tracked=4239 |
| Archive validator | `valid=true`, archive index 31 files |
| remote main verification | matches local `HEAD` |

根目录 CI 已提交并包含 Product、Lab、Archive、boundary 与 composition gates；GitHub runner 尚未替代
本地检查执行，因此“CI 配置存在且可静态校验”不等同于“远端 workflow 已成功运行”。

## 尚未在本次整理中解决的事项

Product `docs/TECH_DEBT.md` 中标记为 `NEEDS_REVALIDATION` 的问题仍需独立行为 Goal/PR，例如
continuation 状态、cache miss 后 Host continuation、validation token 生命周期、projection purge/
rebuild、OpenWorker HTTP auth/exposure、resolver lexical-language assumptions、trace ownership 和
CAS blob orphan 风险。它们不应借重组提交顺手改变行为。

## 恢复与下一步

- 结构重组整体恢复：`git switch --detach pre-codebase-reorg-v1` 或从该 tag 建临时分支。
- 单个拆分可按上表 commit 回滚；不要重写远端 `main`。
- 新行为修改必须在 Product/Lab 各自边界内开独立变更，补充 before/after 测试、公开 API diff、
  trace/golden 证据与 package/integration smoke，再更新本报告或对应结果文档。
