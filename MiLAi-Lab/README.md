# MiLAi Lab

r52同版本开发实验与140项终态回填已完成，功能验收仍PARTIAL，没有稳定推荐配置，Product NO_GO。原L1为24/24 PASS；新增合同L1 23限定通过／1失败，L2 9／3，L3形成41／16、读取17／13，新L4 9／3。来源、时间范围、行动选择及提供方限制按原结果保留。详见[终态报告](docs/V13_5_R52_TERMINAL_REPORT.md)、[FUNC汇总](docs/V13_5_PROGRESS.md)及[验收映射](docs/V13_5_REQUIREMENTS_AND_ACCEPTANCE.md)。

当前隔离开发从 PR82 main `fc1c6c9` 执行完整 MiLAi-Edit 计划：公开 benchmark、共同底座清理、B0/B1/B2/M 四臂比较、保留来源确认及一个最终候选的功能回归。E0 接线已完成，实际 E1 正在运行；按用户指令仅使用现有 Qwen3.6 家族。工程检查不代表方法有效或 Product 验收，见[本轮进度](docs/MILAI_EDIT_PROGRESS.md)及[复现说明](docs/MILAI_EDIT_REPRODUCTION.md)。

MiLAi 的研究、评测与实验代码位于本目录。可部署产品属于
[MiLAi-Product](../MiLAi-Product/)，跨目录规则见
[Source of Truth](../SOURCE_OF_TRUTH.md)。Lab 不导入 Product 私有实现。

## 当前入口

- [2026-10-05 实验进度快照](docs/MILAI_EDIT_CHECKPOINT_20261005.md)：B0/B1 已完成，B2 运行中，M 未开始；实验继续，最终候选与产品验收尚未完成。
- [MiLAi-Edit 原计划](docs/MILAI_EDIT_LITERATURE_AND_EXPERIMENT_PLAN.md)、[分析协议](docs/MILAI_EDIT_ANALYSIS_SPEC.md)和[实现说明](docs/MILAI_EDIT_IMPLEMENTATION.md)：本轮完整执行，历史结论原样保留。
- [v13.5 功能入口](docs/V13_5_FUNCTIONAL_USAGE.md)：自然保存、修订、历史、遗忘及两工作流；[执行协议](docs/V13_5_EXECUTION_PROTOCOL.md)、[验收映射](docs/V13_5_REQUIREMENTS_AND_ACCEPTANCE.md)。
- [当前状态](docs/LAB_CURRENT_STATUS.md)：授权范围、候选证据与未完成项。
- [代码架构](docs/LAB_ARCHITECTURE.md)：职责、依赖方向及兼容入口。
- [项目地图](docs/PROJECT_MAP.md)：从任务定位源码、配置、测试和证据。
- [v12 总体整理报告](docs/CODE_ARCHITECTURE_V12_RESULTS.md)：维护位置、兼容范围和工程证据。
- [v12 整理进度](docs/CODE_ARCHITECTURE_V12_EXECUTION.md)：阶段提交、工程验收和剩余迁移。
- [代码职责](docs/CODE_OWNERSHIP.md)、[依赖规则](docs/DEPENDENCY_RULES.md)、[历史入口](docs/HISTORICAL_CODE_INDEX.md)。
- [PR81历史开发与合并交接](docs/V13_5_DEVELOPMENT_MERGE_20261004.md)：实现、完整通信、三项失败、费用及剩余验收；[r50 部分检查点](docs/V13_5_CHECKPOINT_r50_20261004.md)保留历史分母。
- [历史 v10 实验报告](docs/MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md)：v10 局部结果、R2 失败、成本和限制。
- [结果索引](docs/RESULTS_INDEX.md)：当前与历史结果。
- [贡献约束](AGENTS.md)：文件负责人、检查和发布边界。

PR81 已合并为 `0359fc0`；[PR82](https://github.com/minguselandy/MiLAi/pull/82)继续原计划。
r52 源码 `2166cc7` 的 Fast CI 通过，Full composition 为 skipped；机械检查与模型验收分开记录。
各轮分母和失败独立保留，见[功能进度](docs/V13_5_PROGRESS.md)。
历史[暂停总结](docs/V13_5_PAUSE_STATUS_20261003.md)和 v13.4 Simplify 结论保持，未恢复 T1–T3。
功能入口显式选择 `functional_v1`，旧默认不变。

## Repository roles

| 路径 | 职责 |
|---|---|
| `src/milai_lab/` | 唯一可导入的 Lab 实现 |
| `tools/` | CLI 和历史阶段入口，复用包内实现 |
| `configs/` | 开发和验证配置 |
| `data/diagnostics/`、`data/fixtures/` | 可公开、可审查的小型合成输入 |
| `data/manifests/`、`data/locks/` | 来源身份、冻结、成本和精简结果 |
| `tests/` | 按依赖分组的合同、单元和集成检查 |
| `docs/`、`studies/active/` | 设计、协议、状态和报告；历史 ACTIVE 不构成新授权 |
| `studies/archive/` | 历史材料，不作为活动 import 或构建输入 |
| `artifacts/` | 忽略的原始轨迹、数据库和本地输出 |

第三方源码、模型权重、数据缓存、虚拟环境、DSN 和完整私密轨迹不提交。
旧 runner 的兼容导入只转向同一份 Lab 实现，不复制第二套活动逻辑。

## Quick start

Python 版本和依赖以 [pyproject.toml](pyproject.toml) 与 [uv.lock](uv.lock) 为准。
基础开发依赖与 LangMem 可选依赖分别安装：

```bash
uv sync --frozen --dev
# 仅在修改 LangMem/application 路径时选择对应依赖组：
uv sync --frozen --dev --group baseline-langmem
```

按 [验证矩阵](configs/lab-verification-matrix.json)选择与改动有关的测试；
[矩阵检查器](tools/check_verification_matrix.py)核对源码、可选依赖和 CI 覆盖关系。
不以缺少依赖导致的 skip 代替通过，也不为文档或发布重复整套检查。

```bash
uv run --no-sync python tools/check_verification_matrix.py
uv run --no-sync milai-lab-check-boundary
uv run --no-sync milai-lab-check-tools-boundary
```

涉及包内模块移动时另做包构建与安装后导入检查。真实实验需要独立冻结输入、方法、
模型/工具合同、scorer、顺序和隔离资源；开发检查不会自动开启实验。

## Experiment arm kinds

`PRODUCT_BLACK_BOX` 使用锁定的公开产品接口；`PRODUCT_TESTKIT` 是只读工程诊断；
`RESEARCH_PROTOTYPE` 是 Lab 自有候选；`SIMULATION` 是合成或代理执行。
各类证据不能互相升级；进程退出或工具成功不能替代语义验收。

历史 README 的完整阶段记录保留在
[整理前固定提交](https://github.com/minguselandy/MiLAi/blob/091dcbd48dc1800e5b8cc7f0ee3066dc00a76311/MiLAi-Lab/README.md)，
相关实验报告和锁文件原样保留。复现旧结果应检出其方法/执行提交，不能要求当前源码匹配所有旧冻结。
