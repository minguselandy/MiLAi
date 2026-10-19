# Host 意图检索 v3 执行记录

目标为完整执行 `MILAI_HOST_INTENT_RETRIEVAL_DEVELOPMENT_EXPERIMENT_PLAN_20261019_v3.md`，
当前仅进入 M1；未宣称方法有效或目标完成。旧研究头 `1d568169` 为回滚基点。
本次分支 `feat/host-intent-retrieval-20261019`，独立工作树
`/cra/memory/mx_memory/MiLAi-worktrees/host-intent-retrieval-20261019`。

## 实际实现与边界

- `memory/retrieval_request.py`：query-only 与可选 purpose/evidence/required_points、
  as_of/target_scope/known_evidence_refs、返回/决策上限。身份由已有上下文提供。
  输入 schema 放在 memory，因为包边界要求 contracts 仅使用标准库。
  `memory.functional.StructuredReadGoal` 保留原导入路径。
- `methods/intent_retrieval.py`：在原 Host 注册 `milai_retrieve`，复用
  `run_memory_control`、`EvidenceOperations`、Store 来源/版本和 `_read` 额度。
  Host 调用前不自动取证；工具只返回实际材料、结束原因和用量。
  使用已有 `material_ref` 结构，引用从原 Store 快照重开；未知引用拒绝，遗忘可见性继续生效。
  已取得来源范围单列到控制状态，重复读可省略，旧引用不被当作当前真相。
- 请求和执行反馈使用同一 `operation_payload`，生成视图也获得完整请求。
  Scope 是语义要求，不直接变成访问过滤；未知查询时间不填今天。
- `runners/memory_control.py` 接受调用方持有的模型池；模型加载与逐次前向分别计入原账本。
  NativeDecision 支持显式 device，默认 CPU；未创建模型服务。
- `runners/functional.py` 使用原 Host 图与工具派发；薄入口
  `tools/run_host_intent_retrieval.py` 只准备配置并调用原 prepare/message。
  明确的 native-probe 是 E0 实验强制一次工具调用再回答，方法默认仍允许 Host 自行调用。
- 不更改 Product Schema/API、权限、Canonical、已有保存/更正/遗忘操作。
  无 SHA/checksum/替代内容指纹校验，无子代理，无第二账本，无旧位置重跑。

## 当前证据

63 项相关测试通过（真实 SQLite 来源/引用、原生 ToolMessage、正常 Host runner、
执行后反馈、完整返回额度、已知来源重开与撤销、视图请求传播、模型复用计费，及受影响旧控制器测试）。
它们使用脚本响应证明机械接线，不是模型语义结果。Ruff、包依赖边界和 tools 依赖检查通过。
`--help` 已实际执行；主配置完成离线 prepare（零真实模型调用）。

2026-10-19 实际核查旧调度器 1651723 和 own-train 子进程 2665555 已退出；
`reviewed-followups-dispatch-v10.json` 为 COMPLETED，own-train 为
COMPLETED_WITH_FAILURES 72/72。没有重启或改动其冻结源码、结果与原费用。
旧 V11 只处于已准备未执行状态，本目标没有自动启动它。
旧任务待结算的离线成本仍保留原状态；本次人工阅读/标注未测量，不记作零。

## 完整目标的验收清单

| 要求 | 需要的实际证据 | 当前状态 |
|---|---|---|
| M1/D1/E0：6 历史×2目的×规则/Laya=24 次原生外部调用 | 原 Host 请求、内部 trace、返回、答案、首次失败和成本 | 只准备第一历史 4 个位置，未运行 |
| query-only、丰富请求、跨调用引用和模型反馈 | 接口测试＋实际轨迹 | 机械通过；语义未验证 |
| 六种条件配对＋D2 参数化补搜/范围 | 同池目的、时间、已读、相关/无关更新、排除范围、预算两侧效果 | 未完成；当前 SEARCH 尚只有原请求 |
| FollowIR / 合法 MemOps train / MuSiQue-Full TRAIN | 来源/许可版本、主题背景共享种子分组、实际 Store 状态与偏好 | 未导入；既有 dev 不转 train |
| T0 / T1 / T2＋continued-CE、原生/实际工具评测 | 数据版本、最终权重、tokens、分组结果、0/1/2种子 | 未训练 |
| E1 Host×控制2×2，16组128开发任务及新保留组 | 全部位置和配对区间，允许无调用失败 | 未运行 |
| E2 同请求同before 固定/规则、Jev、生成式 | 原请求冻结、各臂独立后续轨迹、下游结果 | 未运行 |
| E3 等信息文本重训、单次与反馈对照 | 同数据/预算的重训和实际工具结果 | 未运行 |
| E4 InstructIR 完整选定配置 | 官方输入语料、原生检索指标和要求成对响应 | 未接入 |
| E4 LongMemEval-V2-Small 451题 | 原生后端、固定Reader、图像、质量与查询成本 | 未接入；文本子集不替代全量 |
| E4 Mem2Act-small GivenTool 400题 | 相同目标schema、原指标与 strict_call_match/argument_value_accuracy | 未接入；SelectTool 另列扩展 |
| E5 512/2048/4096 工作点与七类缓存工作负载 | 每臂自身缓存，真实交付量、冷暖完整成本 | 未运行 |
| M6 额外Host、版本接口、最终报告 | 固定工具/Jev跨Host结果、逐项要求审计 | 未完成 |

计划中的 SGD/SGD-X、BIRCO、2Wiki、线性头和 SelectTool 按其条件/可选定位保留，
不会把未执行的格子算作完成。不得凭局部测试或文件存在宣布 M1–M6 完成。

## 首条历史与运行

`data/fixtures/host-intent-retrieval-v3-e0.json` 当前仅包含一个作者编写的开发背景：
晨会用西班牙语、周报用英语。两项用户任务分别索取原话和可应用偏好。
每个条件使用独立 bank 中相同的原来源，避免第一回答成为另一条件的额外证据。
离线 review_basis 不进入 Host 输入。数据归属见
`data/manifests/host-intent-retrieval-v3-data.json`。

当前 7860 服务未启用 native-auto tool parser；E0 用服务器支持的命名原生工具调用，
工具名固定，query/可选字段由实际 Host 生成，然后原 Host 接收结果作答。
不能把这种强制调用证据写成自主调用/放弃调用的 E1 成绩。
后续自主实验可用既有 JSON-action 传输，在所有条件保持一致并清楚标注。

```bash
PYTHONPATH=src <existing-cuda-env>/bin/python tools/run_host_intent_retrieval.py \
  configs/host-intent-retrieval-v3.json data/fixtures/host-intent-retrieval-v3-e0.json \
  artifacts/host-intent-retrieval-v3/runs/e0-first-history-v1 \
  --source-version <frozen-local-commit> --native-probe \
  --host-site-packages <existing-http-env>/lib/python3.11/site-packages
```

占位路径须替换为已存在环境；真实运行从本地提交的冻结副本启动。原始轨迹/数据库/
权重留 ignored artifacts；目前无远端发布或合并。
