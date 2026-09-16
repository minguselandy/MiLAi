---
date: "2026-09-14"
goal_id: MILA-HOST-MEMORY-CONTROL-REPAIR-01
status: DEVELOPMENT_COMPLETE_BENEFIT_NOT_ESTABLISHED
method: milai-rwc-v0.2
terminal_adapter: hiagent-method-adapter-v0.4.2
kind: RESEARCH_PROTOTYPE
model_allocation: CLOSED
benefit: NOT_ESTABLISHED
---

# Host 记忆调控修复开发结果

本轮已实现去重材料区、独立卡片、Controller 路由、普通同结构对照，以及本地和公开
Working State 交接。真实公开恢复已通过，一项原生任务完成同版本配对；
最终完整回归为 **4573 通过、1 可选依赖跳过**，工程开发完成。
这是 [修复 Goal](MILA_HOST_MEMORY_CONTROL_REPAIR_GOAL_v1.0_20260914.md) 的开发结果，
不把工程完成当作记忆政策收益。使用入口见
[HOST_REVERSIBLE_WORKSPACE](../../docs/HOST_REVERSIBLE_WORKSPACE.md)。

## 实现与直接验证

| 缺口 | 本轮实现 | 证据 |
| --- | --- | --- |
| 同一回执反复展开 | 来源按 ref/revision/范围进入唯一材料区，历史及 Frame 只引用正文 | 用旧 CONTROL_0 的 13 次实际 Actor 边界离线重装配，原有 12 次重复，新装配 0 次；原始新反馈保留 |
| branch 依附已有段、整版丢失条目 | Host 分配独立 card ID；按条修订和归档、revision、未触及卡片保留 | 首段前建卡、部分修订、归档、恢复、非法引用原子拒绝测试 |
| Controller 只有建议 | ACT/RECALL/DELIVER；回读后重新调控，分开记录 Actor/Controller 反馈位置 | 单元路径和真实公开恢复路径覆盖回读；原生候选出现一次合法 DELIVER |
| 缺少同结构普通政策 | WORKSPACE_SIMPLE 与 MILAI_RWC 共用循环、Actor、工具、默认容量及预算 | 两种政策参数化测试、真实 Provider MockTransport 记账和一项原生配对 |
| 只有进程内交接 | 公开 SDK GET/UPDATE、原子压缩 archive、CAS、命名空间与依赖保留 | 真实隔离 API/PostgreSQL，两个 OS 进程保存和恢复，无本地检查点捷径 |
| 恢复边界不完整 | 未知动作不可保存；恢复前完整校验；来源失效时模型调用前停止；摘要缓存可恢复 | 损坏检查点不留下部分状态，来源撤销阻止摘要/Actor/检查点，调用数与未处理反馈续接 |

`CONTROL_0`、`H_ONCE`、`INCREMENTAL`、`EVIDENCE_0/1` 保持独立可选。
Lab 核心不导入产品包，没有修改 Runtime、公开 Schema 或 benchmark 标准答案。

## 有限原生模型运行

固定 Harbor 0.23.0 和既有模型 HTTP，Qwen3.6-35B-A3B-FP8、thinking=false、seed=213。
同一模型承担 Actor/Controller/摘要，输出上限 4096/2048/1024，所有类别和失败共享每轨迹
64 次额度，串行执行。四个位置全部结束，没有第五次模型轨迹。

| 任务 | 政策 / 方法版本 | Actor / Controller / 摘要 | tokens | 原生结果 |
| --- | --- | ---: | ---: | --- |
| cancel-async-tasks | WORKSPACE_SIMPLE / v0.1 | 1 / 1 / 0 | 2,383 | 首步 subgoal 接线冲突，业务未执行，无评分 |
| cancel-async-tasks | MILAI_RWC / v0.2 | 6 / 6 / 4 | 36,614 | 自测命令 10 秒超时，Host 停止，无评分 |
| multi-source-data-merger | MILAI_RWC / v0.2 | 4 / 5 / 2 | 47,691 | reward 1；3/3 通过 |
| multi-source-data-merger | WORKSPACE_SIMPLE / v0.2 | 5 / 5 / 2 | 49,264 | reward 1；3/3 通过 |

总计 **41 次生成、135,952 tokens**，无未知模型用量、无未结请求；未用 **215 次额度关闭**。
首波停止后未运行的候选位置由 `native-cancel-rwc-v02` 使用一次，没有额外普通政策重试。
业务终端超时与模型用量分别处理：后者明确，不代表前者的副作用可以安全重放。

首步问题来自新 Actor 的“可选 subgoal”与旧 HiAgent 必填逻辑冲突，修复为 Host 按 Frame
意图分配首段，未注入具体任务解法。v0.1 失败证据保留；取消任务既跨版本又缺评分，
不能算成功配对。数据合并的一次同版本配对中，候选少 1 次生成、少 1,573 tokens（约 3.2%），
分数相同；不能据此证明稳定净收益。

16 次实际 Actor 输入均无同身份正文重复。候选与普通政策均实际创建过卡片、选择过材料。
但 17 次 Controller 返回仅 7 次被接受，10 次遭拒绝（包含 v0.1 首次失败）；v0.2 也有
9/16 次拒绝，原因包括缺失字段、未公布的卡片、无草稿 DELIVER 等。拒绝保留旧工作区并
显式交给 Actor，是故障处理证据，不是成功维护。原生四条轨迹均没有自然 RECALL 或分支返回。
当前应保留普通政策，研究重点仍是降低无效控制输出、观察实际回读需求及验证收益；
本轮不自动开启新矩阵、迁移实验或默认启用候选。

## 公开持久恢复

总 `product.lock.json` 与当前产品工作树不匹配；原锁未被本轮覆盖。
本轮单独固定 `data/locks/workspace-rwc-repair-product.lock.json`，保存了原锁不匹配证据，
并在真实产品写入前及完成后验证实际树与公开接口。源码树摘要为
`515d648674e85e6048a9c7b05a754d1743561fb47b5bdf8cda7f0d19a2e6d3af`。

最终 `public-v5` 完整生命周期 PASS：

- 一个真实文件动作后保存未处理回执、外部新约束和独立卡片；另一个 OS 进程只经公开
  Working State 取回完整 archive，再进入 Controller。完整原始回执超过第一页，分页回读成功。
- 文件动作累计只执行一次；原始/外部反馈、卡片、调用数都保持。模型 HTTP 为 0；
  保存与续接共 8 次脚本回调，已结束任务换新目标另用 2 次回调，用于验证接线，
  不是实际 LLM 决策。新目标恢复同时清除 Host/工具层的结束状态和旧交付文本。
- 实际公开 CAS 冲突为 `STALE_WORKING_STATE`；真实提交后人工丢弃 acknowledgement，
  新适配器先阻止重发，再以公开 head 的 operation ID 和 digest 确认已提交。
- 不同 scope 无法取得旧 checkpoint；Evidence 撤销后 Runtime withheld 整份 payload，
  适配器同时拒绝读取与覆盖。其他命名空间和已有 Evidence 依赖在后续保存中保留。
- API 与本轮 PostgreSQL 容器已停止，运行所属数据卷保留为证据。没有操作共享模型服务。

开发期间两次 SDK 启动配置问题均发生在 SDK 请求前；修正了测试入口的 token 传参和显式
close 用法。另一次故障注入包装器的 Python 方法绑定错误发生在 CAS 试验发送前，保存/
跨进程恢复已通过。失败日志保留，最终完整生命周期在新实例重跑通过，没有重放未知业务动作。
最终完整实例有 22 次 SDK 尝试（21 返回、1 次预期 CAS 拒绝）；此前包含包装器故障的实例
有 13 次 SDK 尝试，其中 1 次在进入 SDK 方法前因参数绑定失败，不能算作真实 HTTP。
后续检查新目标恢复时，`public-v4` 暴露传入 checkpoint 的 receipts 字典与运行态共用引用；
已修复导出快照及恢复注册表的共享引用，`public-v5` 完整重跑通过。五个实例的全部 SDK
尝试共 66 次（其中 1 次是进入 SDK 前的包装器参数错误），四个已执行保存的独立世界各有
一次文件动作，累计四次，均没有在恢复时重放。五个项目均无遗留容器。

最终适配器是 `hiagent-method-adapter-v0.4.2`。原生配对使用当时冻结的 v0.4.0，两臂 30 份
实现文件完全相同。此后的两个文件修复仅涉及新目标恢复和检查点副本；它们由最终 128 项
邻近测试及 `public-v5` 覆盖。不能声称最终文件字节与原生运行副本全部相同。

限制：压缩后整个 State payload 仍限 65,536 字节，解压 archive 限 8 MiB；超限失败，
没有假造大对象后端。当前公开版本没有 Working State operation 查询 API，head 标记不匹配、
已被覆盖或不可读时无法自动确认 UNKNOWN。调用者须保留同一业务环境并只允许一个 Host
继续。真实 TTL 到期、任意崩溃续跑和模型自然利用公开恢复均未在本轮实测。

## 工程检查与证据

boundary、ruff、mypy（44 个源文件）、build 已通过。最终完整 pytest 按固定互斥清单覆盖
全部 **4574 个测试：4573 通过、1 可选 Host SDK wheel 跳过，0 失败/错误/遗漏/重复**。
最长单测本轮耗时 2537.23 秒（约 42 分钟），完成后才结项，没有省略或缩短它。
最终清单对应 915 份源码/配置的摘要保持一致；128 项邻近测试是其中的重叠验证，不再加到总数。
旧 CONTROL_0 全回归单独终结为 4520 通过、1 跳过，不能代替新方法验收。

第一次分片期间，一项测试被同期打包清单修改触发关闭时漂移检查；另一项历史冻结测试
也因这项 `pyproject.toml` 改动拒绝进入。已撤回非必要的打包条目，保留独立锁在完整检出中，
核对历史依赖重新相符；中间一次慢测被显式中断。所有失败/中断证据保留。最后两个恢复
修复新增了 2 个用例，最终收集 4574 项；慢测本身及其 62 份实际依赖均未被恢复修复改变，
核对摘要后让它继续，其余所有 4573 项在最终代码上重新执行。不将早先通过的普通分片
直接计作最终版本验收，也不把不同依赖字节混算为同版本结果。

所有原始日志位于 `/cra/memory/mx_memory/evidence/workspace-rwc-repair-20260914-ZlQDKW`：
`development-terminal.json` 汇总全部轨迹与费用；`projection-audit.json` 为旧事件离线装配；
`public-v5` 保存最终公开接口、不同进程、新目标、撤销与清理证据；`handoff-inventory.json`
为最终固定测试清单，`slow-test-final-source-compatibility.json` 记录慢测的未变依赖。
`handoff-verification.json` 记录全部测试身份、每个分片终态、唯一跳过原因和源码一致性。
紧凑仓库记录见 `data/results/workspace-rwc-repair-20260914.json`，原始轨迹不进入 Git。
