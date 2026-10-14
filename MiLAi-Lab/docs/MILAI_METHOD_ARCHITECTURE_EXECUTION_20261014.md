# 方法架构 v3 执行记录

原始目标是执行 `MILAI_METHOD_ARCHITECTURE_EXPERIMENT_PLAN_20261014_v3.md`，当前仍未完成。
研究分支 `feat/lab-method-architecture-20261014` 从最新可读开发头 `8293a4e7` 建立。
本记录只说明已实现和已核验的第一切片，不把机械测试当作模型语义成绩。

## 首切片 `32ffb69f`

- `methods/dependency_memory.py`：从模型选择的实际根目标沿现有条件/例外关系计算潜在影响区域，将上游条件和明确保留的后继列为只读上下文。改变 A 不会仅因共享条件而把 B 纳入修改；改变共同条件则会重新判断各后继。范围不重叠/其他支持仍成立目前由模型选择 preserve，不以词面规则推断。
- `EditFeatures.dependency_updates`：显式启用新更新策略。一次 impact 选择后使用原 single-pass Editor，约束已有节点的修改范围，沿原 MemoryService 提交。形成仍由模型完成；无旧节点时不增加 impact 调用。规划和区域随原维护结果落盘，实际 before/after 与回执继续走原产物。
- `methods/evidence_reading.py`：用相同关系选择查询根的条件/例外，不展开无关兄弟命题；模型可选实际旧版本。历史包打开真实旧状态，并将当前/历史修订的变化证据加入支持，包含已经离开当前图的撤销事件。历史包不会被当前刷新覆盖。
- Benchmark 的 `dependency_reading` 将上述选择接入原 Evidence Pack 和共同 Reader。选择调用使用原 provider/账本，计入同一每题调用上限；原始问题不变，读取选择不写回状态。

当前仍完整交付已定位记录供 impact 判断，尚未证明局部上下文带来成本收益。
首切片只使用现有 `modifies/overrides`，当时未实现显式 AND/OR 支持组、模型建组持久化和跨记录传播。第二切片的单记录支持组实现见下文；跨记录传播仍未完成。
新读取决策目前由 Benchmark 调用；共享函数可用于 Host，但正常 Host 的读取选择尚未接入，不能称 W5 完成。

## 新数据和可执行入口

`data/fixtures/milai-method-architecture-dev-v1.jsonl` 包含借展双站、种子共享柜两条作者编写的开发链，各 6 个原文事件、6 个查询。覆盖未来生效、撤销原因、事实更正与初存版本、非目标保持、替代支持、未决模态。Writer 使用既有 `halumem_session` 的来源投影，问题/答案留给评价路径。

两配置共用来源、时间候选、分词、模型、T1、8192 输出、65536 上下文、12 次调用上限和原连续账本。普通命题 B1 与候选 M 的差异包含表示/更新/读取，因此仅是首轮开发比较，不能识别 2×2 交互。预备入口使用 HaluMem 数据协议，不代表数据是官方 HaluMem，也不把其成绩列为外部 benchmark。

```bash
cd /cra/memory/mx_memory/MiLAi-worktrees/method-architecture-20261014/MiLAi-Lab
export PYTHONPATH="$PWD/src"
PY=/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python
$PY tools/run_baseline_alignment.py configs/milai-method-architecture-dev-v1.json artifacts/method-architecture/continuous-v1/candidate --phase prepare --benchmark halumem --runtime-dir artifacts/method-architecture/runtime
$PY tools/run_baseline_alignment.py configs/milai-method-architecture-plain-v1.json artifacts/method-architecture/continuous-v1/plain --phase prepare --benchmark halumem --runtime-dir artifacts/method-architecture/runtime
```

两条 prepare 已完成，均为 `PREPARED_ZERO_MODEL`，每臂 12 会话、12 QA。predict/score **未运行**。
这些配置用于各臂独立形成的连续轨迹；E1 要求的同一实际 before 诊断仍需先形成真实种子并完成信息等价的普通命题投影，不能用两条独立轨迹替代。

## E0 只读核对和运行限制

已直接读取旧 S0 的 terminal-predict、terminal-score 和逐题评分文件：132 会话，9 答复、3 次 read_call_limit 缺答，首次评分 7 Correct、2 Hallucination、3 缺答。109 个原请求都有响应；逐响应 usage 复算为 Reader 100 次/3,652,278 tokens，Judge 9 次/24,602 tokens。

旧 pack 没有预测/评分终态，8 请求全部有响应，已观测 Reader 363,114 tokens，不能将部分输出当完整比较。实际检查 `/proc`，驱动 1376965 和工作进程 1626865 均为 T；尝试非阻塞取得原账本 owner lock 明确失败。旧实验保持用户暂停状态，没有发送信号、重跑或重评分。新实验也未绕过锁、重置账本或创建第二账本。

机器记录在 `data/manifests/method-architecture-v1-checkpoint.json`。下一次调度必须重新检查活进程与锁；旧状态文件不能代替进程证据。

## 验证与尚未满足的要求

直接 SQLite 测试覆盖共享条件方向、保留后继、真实局部提交、非目标和旧版本保持、重复请求不重采样、当前根撤销后的刷新、旧版本/撤销来源交付，以及通过正常 Benchmark 接入共同 Reader 的两次调用预算。
当前相关用例合计 54 项通过（依赖 6、Evidence Pack 17、v2 runner 31），6 个修改源码模块 mypy、Ruff、包 DAG 和工具依赖边界通过。扩展旧机制测试 17 项通过、1 项失败；失败 `test_controls_retain_actual_revisions_without_ideal_initialization` 在原 `8293a4e7` 工作树也复现，是旧诊断夹具无 `source_ref` 触发读取错误，未改服务来绕过它。

| 方案要求 | 当前证据与后续工作 |
|---|---|
| W0 / C1 共同条件和隔离 | 独立分支、两配置、新输出根、prepare；旧确认原样。实际模型闭环尚未运行 |
| W1 / C2 影响与只读上下文 | 已接维护和提交，直接测试通过；新故事真实模型输出、AND/OR 支持组及最小跨记录切片待做 |
| W2 / C3 共享关系与历史补证 | 已接 Benchmark 和共同 Reader，SQLite 旧状态/撤销证据验证；替代支持组机制和真实模型选择评价待做 |
| W3 生命周期策略 | 每事件维护沿用；明确变化维护、查询时重建及复用次数/规模曲线待做 |
| W4 训练选择 | 等待真实断点；匹配训练数据对、转换质量/关系目标比较待做，不启动 CPU FP32 大模型路径 |
| W5 / E5 Host 迁移 | 更新核心共享；正常新故事、读取选择和首次/恢复结果分表待做 |
| E0 效率证据 | 关闭的 S0 已只读核对；pack 暂停，无完整比较，不从部分结果推断胜负 |
| E1 最小两臂 | 新源链和连续配置准备；同真实 before 的投影诊断与原始输出/语义审查待做 |
| E2 / E3 | 约 12 独立链、UJS、2×2、对称重复、必要消融待做；不先扩大全矩阵 |
| E4 | 独立长历史、额外模型族或规模、外部 HaluMem/LongMemEval/MEME 适配与原口径评价待做 |
| 第6/8.4节近邻 | 一手全文和代码条件核对、选择适当外部强基线待做；没有声称完成复现 |
| 第10/12.2节结果 | 原 HTTP 计账和 before/after/回执复用；UJS、来源忠实、QA、簇区间和生命周期报告尚无新实测 |
| C4–C6 / 第13节 | 机制对照、训练/跨记录、独立验证、图表与证据一致的论文主张待做 |

当前无新模型质量结论，Product/Archive、公开 API/权限/Canonical 行为未改变；没有 SHA 校验、新数据库或在线审核代理。没有推送 GitHub、远端 CI 或合并。工作仅在研究分支，基线提交可用于回看和回退。


## 第二切片：模型支持组与保留主张的依赖更新

本切片增加 `EditFeatures.dependency_groups`，与 `dependency_updates` 独立开关。Writer 可从实际来源输出小型支持组：组内 AND，组间 OR。create/rewrite 使用本次生成的 clause 索引，程序在条件展开后绑定真实 unit ID；局部编辑使用实际旧 u 别名和本次生成节点的 n 别名。持久 ID 仍由程序生成，组与单位文本在原记录的同一版本事务提交，没有新数据库。

局部更新有三个具体行为：

1. 删除一个前提会删除包含它的整条 AND 路径，保留其他 OR 路径。所有路径失去后，空组明确保留，目标主张不会被程序改为相反事实或自动撤销。
2. 修改前提正文/归属但保留节点 ID 时，将依赖该前提的组标为需要重新解释，避免旧关系被当作新正文的既定证明。显式新证据下重新设置组可解除该标记。
3. 保留派生主张正文时仍可更新它的支持组：`support_update_targets` 与正文可改集合分别约束。这样另一条支持继续成立时不必重写结论，却能维护变化的依赖。

查询支持选择接收各目标的 route indexes，一次打开完整 AND 路径，不会因逐节点排除而丢掉其中一个必要前提。未指定的组保留全部路径供判断。支持组来源纳入原有来源可见性、Reader 原件交付和成本路径。记录更新后若组发生变化，旧 route index 不复用于新版本；重新打开新版本候选，历史版本仍精确保留。

三值支持计算在已知适用性输入下区分 supported/unsupported/unknown；Reader 当前只把明确时间不适用映射为 false，其余仍要求来源解释，不把图存在、报告时钟或模型断言自动当作事实成立。

直接测试走实际 SQLite 与原公开提交/读取路径，覆盖生成 clause 索引在条件展开后的绑定、替代路径、前提变更、整条 AND 删除、新节点参与组、只改关系的版本提交、旧版本不变、正文保留时允许关系更新、历史选择刷新和来源撤销传播。遗忘沿用既有边界：撤销组的唯一来源会隐藏其关联记录及历史，未放宽为旧版本可绕过遗忘。

新的 `milai-method-architecture-{dev,plain}-v2.json` 已在 `artifacts/method-architecture/continuous-v2/{candidate,plain}` prepare；每臂仍 12 事件、12 QA。原 v1 配置和 prepare 保持原样。v2 只有机械验证，无真实模型形成图、答案或 UJS 结果。

本切片不完成 E1：还需要同一真实模型 before 的信息等价普通命题投影和实际两臂原始输出。关系形成准确性、自由文本作用域选择、跨记录部分提交、正常 Host 读取迁移、训练和外部评价仍待执行。B2 全量重写的支持组精确保留接口也尚未作公平性实测，不能凭当前局部编辑测试宣称完整表示矩阵已经就绪。

第二切片最终相关验证：267 passed、4 条既有 LangGraph/LangChain 弃用警告（84.52 秒）；6 源码模块 mypy、Ruff、包 DAG 通过。此前旧机制夹具的 source_ref 失败不在此 267 项中，仍保留首切片的基线复现记录，没有据此声称全仓通过。新模型请求产物仍为 0。机器记录：`data/manifests/method-architecture-support-groups-v2-checkpoint.json`。
