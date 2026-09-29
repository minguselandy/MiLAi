# MiLAi Lab 架构整理记录

2026-09-29。用户授权梳理当前项目、优化代码架构并提交 GitHub，并明确要求使用 Sol。
本次在 `091dcbd48dc1800e5b8cc7f0ee3066dc00a76311` 上建立独立工作树和
`refactor/lab-architecture-20260929` 分支。Sol xhigh 负责源码、配置、测试和必要 CI，
Root 负责项目梳理、文档和验收，Luna high 负责 Git 发布。原实验 Goal 保持 paused。

## 问题与选择

基线可导入包有 165 个 Python 文件、48,404 行；`langmem_foundation.py` 424 行，
`langmem_application.py` 826 行。文件长度只是线索，实际断点是职责与依赖：
`methods.memory_lifecycle` 为复用 journal 导入 runner，world/schema 消费者也会连带
加载阶段编排依赖。另一种解释是这些只是必要编排代码，按行数切分并无收益；因此
本次只提取已有可复用能力，保留 `run_phase` 和 writer cadence，不拆所有历史大文件。

另外，README 和当前状态页分别有 535、1,166 行，顶部仍称早期实验 ACTIVE/当前主线。
这容易把历史研究目标与当前暂停状态混淆。现在入口按当前授权、实现职责与证据导航组织；
原文在固定基线提交中完整保留，各实验报告、原分母、冻结输入和锁文件不重写。

## 改动合同

- `application/journal.py`：原 journal 和可选保护，一份实现。
- `application/world.py`：标准库 SQLite 合成业务世界。
- `application/tools.py`：原 schema、adapter 和 owner 绑定。
- `application/recovery.py`：原 pending 查询恢复逻辑，不依赖 runner。
- 旧 runner 导出同一对象，编排继续留在原路径；直接消费者使用 canonical 路径。
- 身份收集覆盖提取后的真实实现，防止仅哈希旧兼容外壳；不改历史锁。
- 当前 README、状态、架构、项目地图和结果导航相互链接，历史状态不授权实验。

整理后两个 runner 分别为 9 行和 552 行；包内共 170 个 Python 文件、48,487 行。
新增行数来自明确的模块边界、兼容导出和类型合同，不宣称总代码量下降或运行性能改善。

没有改变业务参数、异常、请求/回执、journal/SQLite/Store 合同、默认开关、模型配置或
实验预算；没有补写 R2 的真实失败。结构清晰和工程检查不证明记忆语义变好。

## 验收记录

局部工程验收已完成，详见[机器可读清单](../data/manifests/architecture-refactor-20260929.json)。

| 检查 | 结果与范围 |
|---|---|
| 既有移动合同 | 21 项通过，含四类真实子进程 MockHTTP 恢复场景；无真实推理 |
| 架构、身份与直接消费者 | 10 项通过，覆盖旧入口同对象、轻量 world、禁止 application 导入 runner、实现哈希遗漏/篡改拒绝 |
| 基线对照 | 10 个定义 AST 相等；schema、业务回执/catalog/SQLite 和 journal 输出对照相等 |
| 静态检查 | 相关 Ruff、mypy、验证矩阵、包边界和 tools 边界通过 |
| 离线发行包 | 从 sdist 构建 wheel，包内 canonical 源码相同；隔离安装后的导入与无 site-packages 的 world 导入通过 |
| 文档与保留资产 | 本地链接、JSON 和差异检查；原实验报告、历史锁、原工作树草稿与连续账本保留 |

共 31 个相关 pytest 节点通过，没有运行全量测试、benchmark 或语义评分。
构建复用既有环境和缓存 backend；没有安装新依赖或下载。
原始日志、对照输出和构建产物保存在忽略的 `artifacts/architecture-20260929/`，
公开清单只保留必要命令、结果与哈希，不上传数据库和本地构建产物。

首次检查中的 Ruff 导入排序及正则原始字符串标记和 mypy 的 `uuid` 显式导出问题已修正。
首次离线构建在加载 backend 时缺少缓存 `tomlkit` 的搜索路径；补齐既有缓存路径后通过。
这些失败留在工程证据中，不计作模型调用。Root 首次静态盘点误将 LICENSE 当作 Python
解析，限制为 `.py` 后完成；没有改变源文件或实验数据。

本次真实 Host、embedding、Judge、PostgreSQL 调用和实验均为 0，没有调整既有服务。
连续账本 SHA256 仍为 `7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`。

## 保留与边界

原 repair-v10 工作树、九个未跟踪 R2/R3 草稿及原 v27 草稿保持原样。
历史 README、当前状态和架构原文可通过 `git show 091dcbd:MiLAi-Lab/<path>` 或
各新页面的固定 GitHub 快照链接查看。没有删除历史报告、实验世界或错误记忆。

旧阶段大 runner 与外部 baseline→SDK runner 依赖仍存在；它们有不同契约，未为目录
一致性而批量重写。本次只收敛当前应用职责边界。Product 仍 NO_GO；PR 发布不合并
main/旧 PR，不恢复实验。该分支以已发布报告分支为 base 独立提交供审查。
