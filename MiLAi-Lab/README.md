# MiLAi Lab

MiLAi 的研究、评测与实验代码位于本目录。可部署产品属于
[MiLAi-Product](../MiLAi-Product/)，跨目录规则见
[Source of Truth](../SOURCE_OF_TRUTH.md)。Lab 不导入 Product 私有实现。

## 当前入口

- [v13.5 功能入口](docs/V13_5_FUNCTIONAL_USAGE.md)：自然保存、修订、历史、遗忘及两工作流；[执行协议](docs/V13_5_EXECUTION_PROTOCOL.md)、[验收映射](docs/V13_5_REQUIREMENTS_AND_ACCEPTANCE.md)。
- [当前状态](docs/LAB_CURRENT_STATUS.md)：授权范围、暂停状态与未完成项。
- [代码架构](docs/LAB_ARCHITECTURE.md)：职责、依赖方向及兼容入口。
- [项目地图](docs/PROJECT_MAP.md)：从任务定位源码、配置、测试和证据。
- [v12 总体整理报告](docs/CODE_ARCHITECTURE_V12_RESULTS.md)：维护位置、兼容范围和工程证据。
- [v12 整理进度](docs/CODE_ARCHITECTURE_V12_EXECUTION.md)：阶段提交、工程验收和剩余迁移。
- [代码职责](docs/CODE_OWNERSHIP.md)、[依赖规则](docs/DEPENDENCY_RULES.md)、[历史入口](docs/HISTORICAL_CODE_INDEX.md)。
- [r46 模型前检查点](docs/V13_5_CHECKPOINT_r46_20261004.md)：实现、CI及当时状态；后续完整通信结果见[功能进度](docs/V13_5_PROGRESS.md)。
- [历史 v10 实验报告](docs/MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md)：v10 局部结果、R2 失败、成本和限制。
- [结果索引](docs/RESULTS_INDEX.md)：当前与历史结果。
- [贡献约束](AGENTS.md)：文件负责人、检查和发布边界。

用户已明确恢复 v13.5 全部后续开发与实验；r46完整通信为9限定通过/2失败，最新结果见[功能进度](docs/V13_5_PROGRESS.md)。
完整功能尚未验收；[暂停总结](docs/V13_5_PAUSE_STATUS_20261003.md)保留为历史检查点。
v13.4 的 Simplify 退出及更早实验的失败、暂停和分母保留。新入口显式选择
`functional_v1`，旧默认不变；Product 仍为 **NO_GO**。

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
