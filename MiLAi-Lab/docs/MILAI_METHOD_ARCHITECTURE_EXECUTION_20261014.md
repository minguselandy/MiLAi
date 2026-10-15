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


## 第三切片：同一真实 before 的 E1 入口

`tools/run_method_architecture_diagnostic.py` 提供 prepare、seed、compare 三个显式阶段，复用 BenchmarkRun、维护核心、共同 Reader 和原连续账本。prepare 已完成；seed/compare 未运行。

本次诊断选择普通命题 B1 从第一条原文形成共同种子。两臂复制实际银行，候选只将 plain_v1 类型和相应展示切换为 conditioned_v1，不改命题正文、unit ID、来源、归属、时间、版本号或原始形成身份，不补条件边、支持组或正确答案。所有种子历史版本也只作同样的展示转换，并将原件与投影并列保存。原 seed 银行保留原样。这是受控表示转换；候选起点没有显式图，不能冒称已证明模型独立形成图的能力。各臂从空库独立形成的 v2 轨迹仍是另一条实验线。

更新原文在独立 arrival 副本中只登记一次，再复制给两臂，保证 Source ID、角色、报告时间和捕获时间一致。每臂执行同一次条件变化，随后回答当前/未来、初存版本、非目标三类问题。初存问题的评价依据是实际种子记录，不把理想原文事实替代实际保存状态。查询与 evaluator 字段不进入维护输入；读取使用统计在两臂都关闭。

共享种子成本只记录一次，arm 的维护、影响选择、证据选择、Reader 和 embedding 成本分别从原 HTTP 回执汇总。未知 usage 和无响应请求单列，后者不直接当作已派发；原连续账本仍是计费权威。这不是独立形成系统的完整生命周期对比。工程完成与状态正确、答案正确、来源忠实继续分列，语义字段待真实来源审查。

正常 Benchmark 的依赖选择若已确认 length 或空正文，会沿既有只读失败口径保留缺答；未取得响应回执仍不重试。补充测试覆盖普通入口和 alignment 入口。

```bash
cd /cra/memory/mx_memory/MiLAi-worktrees/method-architecture-20261014/MiLAi-Lab
export PYTHONPATH="$PWD/src"
PY=/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python
$PY tools/run_method_architecture_diagnostic.py configs/milai-method-architecture-paired-v1.json artifacts/method-architecture/paired-v1 --phase prepare --runtime-dir artifacts/method-architecture/runtime
# 以下两步尚未执行，需先释放旧暂停队列持有的原账本锁。
$PY tools/run_method_architecture_diagnostic.py configs/milai-method-architecture-paired-v1.json artifacts/method-architecture/paired-v1 --phase seed --runtime-dir artifacts/method-architecture/runtime
$PY tools/run_method_architecture_diagnostic.py configs/milai-method-architecture-paired-v1.json artifacts/method-architecture/paired-v1 --phase compare --runtime-dir artifacts/method-architecture/runtime
```

本切片相关 56 项通过（14.19 秒），3 文件 mypy、Ruff、包/工具依赖边界通过。SQLite 端到端测试使用明确的模型桩，不计真实模型成功。此前 267 项属于第二切片验证，本次不冒称重新运行全套。机器记录为 `method-architecture-paired-v1-checkpoint.json`。

连续三个目标回合实际核验同一阻碍：旧驱动 1376965、工作进程 1626865 均为 T，原账本 owner lock 被占用，结束旧暂停队列的许可尚未收到。旧 S0 109 请求/109 响应，pack 8 请求/8 响应，无缺失响应文件；进程仍未关闭。未发信号、未创建第二账本、未重跑或重新评分旧确认。E1 的下一步需要真实模型反馈，不能用继续增加离线功能或 mock 通过代替。

## 近邻一手输入条件核对

本轮补查了原方案未打开的 PACMI 正文，以及 APEX-MEM 官方论文和 SimpleMem 原论文/作者仓库；没有运行外部方法，也未宣称完整复现。

- PACMI 明确以标注的预更新依赖图为输入，诊断集是固定两跳、六条旧记忆；其传播指标不能直接证明从原文建图的优势。已核对 §1 的 A1–A3、§4、§5 和 Appendix A。我们的模型形成图与正确图上限必须继续分表；本文并未证明 MiLAi 已优于它。[PACMI v1 正文](https://arxiv.org/html/2610.05732v1)
- APEX-MEM 将对话归入实体/事件属性图，保留追加历史，在查询时消解演变。若在共同条件下适配，需要分别计入构建和多工具读取；当前未从已核验的 ACL 页面及 PDF 确认官方可执行代码入口，不把第三方同名项目当作者系统。[ACL 官方论文](https://aclanthology.org/2026.acl-long.749.pdf)
- SimpleMem 原论文有压缩、会话内综合和意图检索三个阶段；作者仓库当前还含多模态和演化检索组件。后续必须固定所用文本路径和实际版本，避免拿当前整个仓库当原论文系统。[原论文 v3](https://arxiv.org/html/2601.02553v3)、[作者仓库](https://github.com/aiming-lab/SimpleMem)

本地已有 `integrations/memory/simplemem.py`，但历史 `dependency_identity()` 会计算源码 SHA，因用户要求本轮未调用它。外部实验前应改为实际源码身份与接口检查的无 SHA 路径，再验证可执行性；目前不能称 SimpleMem 已适配到这轮实验。其他 W3–W5、E2–E5、统计、外部确认与论文结果工作仍未完成。


E1 正常 seed 入口已实际尝试准入，进程退出 1：`BenchmarkRun.__init__` 在原 `budget.json.http-owner.lock` 的非阻塞 flock 处得到 `BlockingIOError [Errno 11]`。这发生在模型调用、账本用量预留和种子银行创建之前；新 request 文件数为 0，bank 未创建。错误原件保留为 `artifacts/method-architecture/paired-v1/seed-admission.stderr.log`。这是运行资源阻碍，不是模型形成失败或语义得分。

本次代码本地提交后，将从该提交保存 `paired-source-v1` 源码副本，身份记录在 `artifacts/method-architecture/paired-source-v1.json`。资源解除后实际 seed/compare 应使用该副本的 tools 入口和 PYTHONPATH，原失败准入日志保留；不在真实运行中热改方法。没有 SHA 校验或新的模型服务。


## 第四切片：SimpleMem 无 SHA 身份路径（2026-10-15）

`integrations/memory/simplemem.py::dependency_identity` 已去掉源码 SHA 计算、固定历史提交拒绝和 diff 拒绝。现在记录实际 Git 身份、声明的历史身份、工作树改动、Python 模块清单和实际依赖版本。未把不同代码冒称旧身份；真正导入路径、接口、方法参数、owner 和资源约束仍在各自使用处处理。此变更只涉及 Lab 依赖报告字段，不改 Product API、权限或 Canonical 行为，也不迁移旧实验的 scope 文件。

本地原生源码实际身份为 db80b6a，工作树无改动，记录 159 个 Python 模块，没有读取源码正文做摘要。新测试在真实临时 Git 工作树中改变已跟踪模块并加入新模块，同时禁用 SHA 和 read_bytes 调用，证明不同身份/工作树改动会被记录而不会变成校验门禁。

默认实验环境缺少 LanceDB、pylance、pyarrow、dateparser、tantivy。已在 ignored 的 `artifacts/method-architecture/simplemem-env` 创建独立环境，安装仓库现有锁定清单中的 13 项附加依赖，通过只在该环境新增的 .pth 复用已有 runtime。原环境再次核对仍未安装这五项，未被修改；未部署模型或服务。

实际原生 SimpleMem、LanceDB、Tantivy 配合 MockHTTP 验证 20 passed、3 deselected、3 条既有弃用警告，7.48 秒。覆盖原文输入、40/2 窗口、尾部 flush、实际持久 ID、三路检索、有限反思、重开、owner/范围及计量；未运行被排除的 memsyco/merit 测试，也未执行它们的 SHA 路径。Ruff、1 文件 mypy、包 DAG 通过。该 SDK 检查不是新研究的实际模型成绩或作者分数复现。

身份与依赖详情保存在 `artifacts/method-architecture/simplemem-source-identity.json`，交付索引为 `data/manifests/method-architecture-simplemem-identity-checkpoint.json`。E1 冻结副本仍是 9bb7d7e1；它不调用 SimpleMem，原准入失败日志保持。

当前运行阻碍已连续四个目标回合实际复核：1376965/1626865 仍为原确认进程且均为 T，原 ledger owner lock 被占用。正常 E1 seed 准入已在模型调用和银行创建之前退出。结束旧暂停队列的请求尚无答复；没有发信号、旁路账本或重跑旧确认。后续的范围判断、训练选择、机制筛选与迁移必须以真实 E1 反馈继续，不能把已完成的离线准备当作整项研究完成。


## 用户继续执行：旧队列释放与首轮真实 E1（2026-10-15）

用户针对“结束旧暂停进程、保留全部数据并释放锁继续 E1”的具体请求回复“继续工作”。已重新核验 PID 与命令行、确认所有既有请求均有响应，备份旧确认的 1068 文件/206662404 字节，再结束默认 SIGTERM 行为的旧驱动及工作进程。1376738/1376965/1626865 均已退出，owner lock 实测可取得。旧 S0 109 请求、pack 8 请求及原响应均未增加；旧 pack 是保留的部分结果，不是完成或重新评分。释放记录见 `method-architecture-old-queue-release-20261015.json`。

E1 使用冻结 9bb7d7e1 和已声明的相同输入/模型/预算执行，seed 与 compare 均退出 0。种子由 B1 模型实际形成，1 记录/4 命题；茶饮偏好虽在完整输入中，却未进入语义状态。两臂共享这个实际缺口，没有人工修补。

| 项目 | 普通命题 B1 | 依赖候选 M |
|---|---|---|
| 初始/最终版本 | r1→r2 | r1→r1 |
| 目标更新 | 写入何雨未来安排及此前沈宁；同一命题包含两个时段，整体 effective_from 的解释需单独评估 | Impact 正确选择 u1，但 Editor 返回 no_change，未来安排未入状态 |
| 已存非目标 | 三个非目标命题原样保留 | 三个非目标命题原样保留 |
| 当前/初存查询 | 核心人物和日期正确 | 核心人物和日期正确，但当前题靠原文补足未写入的变更 |
| 非目标答案 | 核准事实/茶饮值有依据；额外将报告与捕获时间均说成2026-10-15，来源不忠实 | 核准事实/茶饮值有依据，对是否记录了变更过于保守 |
| 新增生成 tokens（不含共享 seed） | 16,194 | 31,325 |
| embedding tokens | 360 | 255 |

共享 seed 1 次/4,131 tokens；全轮实际 13 次生成/51,650 tokens、11 次 embedding/615 tokens、Judge 0。所有实际响应已保存，与原连续账本增量一致；新增 unknown 为 0，原 generation9/embedding1 未知用量基数保留。未重新抽取正确答案或将原文答对等同于状态正确。同一开发者对全部原文与六个完整答案做了对称来源审查，不冒称独立盲审或官方 HaluMem 分数。完整字段和原输出位置见 `method-architecture-e1-v1-summary.json`。

## E1 发现的生成协议缺陷与对称复验

候选的生成 schema 用 partial-object `anyOf` 约束表达“有文本 edits 或有 support_groups”。标准 JSON Schema 接受合法 future append、replace+append，服务内 XGrammar 0.2.3 却拒绝相同完整序列，而接受 no_change；这解释了一个可复现的生成能力缺口，不能只归为模型的范围判断失误。原推理/输出、实际 request schema 和离线检查均保留。该检查仅调用现有服务容器内的 CPU grammar compiler，没有模型 HTTP、额外 verifier 或新服务。

修复将普通 edit 和 group-only edit 展开成两个完整且互斥的对象分支：前者至少一个 edit；后者 edits 为空且至少一个支持组变化。空 edit 仍不合法，单位和支持引用约束保持。修复后的同一示例同时通过 JSON Schema 和相同 XGrammar 编译/字符串匹配。91 项相关检查、Ruff、mypy 通过。

新输出根 `paired-v2` 预声明双方对称复验。复用 v1 真实 seed 与实际 arrival Sources，Source ID/报告时间/捕获时间保持；只复用银行和 seed 结果引用，没有复制 HTTP 输出或再次生成 seed。共享 4,131 tokens 仅全局计费一次。v1 所有结果不变；v2 使用新源码副本，生成温度/容量、问题和 Reader 保持。此修复是工程可生成性修复，不是架构质量或协同已经胜出的证据。


## E1 对称复验与仅状态读取（2026-10-15）

冻结源码463b5182的paired-v2已关闭，复用相同真实seed/arrival。两臂均实际提交r2，并保留已存的三个非目标命题。候选不再返回no_change，说明本轮生成协议已允许并产生实际编辑。普通命题写成一个前后任职复合句、未给显式时间字段；候选也写成复合句，整个单元附effective_from。双方当前/初存核心答案正确，核准条件正确，均对茶饮是否改变给出保守拒断；初始遗漏茶饮仍未手工修复。该起点没有模型形成的关系/支持组，不能用此结果证明建图能力。

| 项目 | 普通命题 | 候选 |
|---|---:|---:|
| 新增生成次数 | 4 | 8 |
| 生成tokens | 18,268 | 40,769 |
| embedding次数/tokens | 6 / 350 | 6 / 370 |
| wall seconds | 77.41 | 154.67 |

新增共59,037生成tokens/720embeddingtokens，原seed4,131只计费一次。各阶段成本与原账本增量全部一致，无新增unknown；原9/1基数保留。原v1结果不覆盖、不重判。

为检验复合时间状态是否实际可读，预声明四次仅状态查询：两臂分别回答4月17日和18日负责人。输入来自实际after，经相同revision_view与共同Reader投影，去掉所有原文支持体，不检索、不形成、不写回。四个核心答案均正确（沈宁/何雨），新增13,977生成tokens、embedding0。普通方案的解释将通用[from,until)约定当作已保存的具体until字段，记为解释忠实性限制；不把核心答对等同于完整忠实，也不凭假设的时间风险继续在同一故事上调参。

以上由同一开发者对来源与全答案审查，不是独立盲审或官方QA标签。完整输出、状态、逐阶段成本及核对结果见`data/manifests/method-architecture-e1-v2-summary.json`。

下一步continuous-v2已启动，使用同一冻结源码，各臂从空状态独立经历两条各6事件故事，12QA/臂，依次predict再首次score。正常维护需自己形成关系，包含临时例外、撤销、替代支持和历史更正。官方HaluMem口径仅用于作者开发数据，独立benchmark评价仍待做。


## E2 独立开发链准备

新增`milai-method-architecture-screening-v1.jsonl`：12条独立作者开发链，六类机制各两条，每链3事件、两次更新后各2题，共36事件/48QA每臂。题材、人物、日期和措辞不同于E1；它仍是机制筛选开发数据，不是独立保留确认。每链有必须改变与必须保持的要求，涉及共享条件的局部例外、OR替代且保留AND前提、两级派生、事实纠错与旧记录、传闻/提案和未来日程。

两臂新配置保持同模型、来源、预算与问题，关闭读取使用统计。评价义务独立放在`method-architecture-screening-v1-protocol.json`，不进入Writer；36个ObservedSession实际解析通过，替换全部评价字段为canary后输入投影逐值一致。两个prepare均PREPARED_ZERO_MODEL，未调用模型，尚未派发predict/score。先完成continuous-v2实际反馈，再确定冻结的筛选源码，不在运行源码上热改。


## 观测断点对应的首批匹配数据对

continuous-v2候选出现两种真实断点：未来变更的replace错误引用并未创建的n0支持目标，整条更新被拒；撤销“管理员在场”时遗留“会员卡通道不加这项要求”，使指代转向前面的培训要求，错误正文实际提交。两个原输出保持。

`milai-method-architecture-matched-training-v1.jsonl`保存两组可审查样例，输入为实际before、当前来源与已到达prior_context，不含测试查询/答案。转换质量目标与关系目标使用相同来源和样本；基线也得到相同纠正事实。人工参考修正均通过原实际生成schema检查，没有应用到原实验银行、重新抽样或重新评分。它们只证明训练数据准备开始，不代表训练有效或W4完成；尚缺正向OR/AND建组样例、独立标签复核、未见范围/顺序评价和匹配训练预算。

当时四张A100 40GB显存占用分别为39,981/39,997/39,901/39,863 MiB；保持现有服务运行，没有部署或训练模型，更没有转向CPU FP32大模型训练。记录见`method-architecture-training-pairs-v1.json`。


## 从空库形成的两故事连续实验：首次预测与评分关闭

`continuous-v2`从冻结463b5182完成双方各12事件、12QA，四个predict/score进程均EXIT0，资源关闭。普通命题首次标签12 Correct；候选10 Correct、2 invalid，后两次Judge原响应为`{}`，未重判。这里只是作者开发数据使用官方HaluMem QA口径，不是外部benchmark分数。

| 项目 | 普通命题B1 | 候选M |
|---|---:|---:|
| 维护生成tokens | 86,887 | 99,364 |
| Impact tokens | 0 | 44,143 |
| 证据选择tokens | 0 | 71,478 |
| 共同Reader tokens | 53,238 | 45,507 |
| 预测总tokens | 140,125 | 260,492 |
| 首次Judge tokens | 33,067 | 30,472 |
| embedding次数/tokens | 32 / 1,393 | 33 / 2,123 |

候选预测生成成本增加85.9%。全队列94生成请求/464,156 tokens、65embedding/3,516 tokens，与连续账本增量逐值一致，新增unknown0；原9/1基数保持。

状态与QA结果不同。两臂都在初始状态遗漏茶饮；普通方案的临时收件例外因EDIT_TIME_SOURCE_NOT_SELECTED被拒，后续no_change不算成功撤销。候选未来人员变更因引用未创建的n0支持目标被拒，临时安排后来可以添加并真实删除，但应恢复的何雨排班始终未写入，保留了旧沈宁状态。两臂的原文混合QA仍能回答人员变更和撤销原因。

种子柜规则的OR凭据和培训条件都保存在正文中；候选在撤销管理员在场要求时留下“会员卡通道不加这项要求”，其前接内容变成了培训。这是已提交的作用域损伤。普通方案正确删去临时条款；不过普通方案曾将未变培训句重新绑定到未重述培训的当前来源，旧h2支持仍保留，来源归属需与文本正确分开。普通方案两道答复把2026捕获时钟当作知识截止时间；候选预约题错说报告于09:00，实际来源是14:00。这些来源忠实性问题与首次QA标签并列，不修改原标签。

两个故事的所有已提交状态均无显式关系/支持组，故当前不能声称模型形成图或依赖传播有效。相同服务XGrammar0.2.3离线检查接受原创建与带支持组的合法创建示例，0模型HTTP；示例只验证语言可生成性，未作为实验状态投喂。未来筛选需观察图是否实际形成，不把人工理想图替代实际before。

完整逐事件状态、回执、答案、首次标签、成本及来源审查见`method-architecture-continuous-v2-summary.json`。未给不完整维度强行汇总UJS百分比；初始遗漏、被拒更新与继承错误单列，避免把缺失例外后的无操作当作撤销成功。

## 已提交作用域损伤的仅状态验证

在评分结束后按事先声明执行四次只读检查，使用两臂实际最终种子柜状态与共同Reader，不给原文、不重新检索、不写回。普通方案核心2/2正确，候选1/2正确。对“会员卡有效但未培训能否领稀有种”，候选实际回答可以，并引用损坏句子解释会员卡免培训；另一题的凭券且培训完成核心结论正确，但解释继续声称会员卡免培训。因此候选两条解释均不忠实于原规程，不能用原文混合QA正确覆盖该问题。

新增4生成/17,126 tokens、embedding0、unknown0，逐臂账本一致。结果见`method-architecture-continuous-bare-v1-summary.json`。没有据此继续在原故事堆提示或覆盖失败结果；两组匹配纠正样例用于后续训练设计，尚未训练。

## E2 实际派发

12独立开发链的screening-v1已用冻结463b5182启动，配置/数据来自7b336663，候选→普通预测，随后各自首次评分；每臂36事件/48QA，关闭读后使用反馈，原连续账本串行HTTP。源码没有热改，先前失败与全部原件保持。该实验将检查新场景中实际关系形成、状态维护与完整成本，不是保留确认或2×2归因。进程状态以ignored目录driver.json与实际PID为准。


## 后续2×2的共同历史候选入口

新增纯读取入口`fixed_history_candidates`，供受控R因素实验把相同实际当前/历史版本开放给两种读取方式。它按输入检查点的真实版本号限制历史，重开当前可见的原版本，移除单一命中单元导航以允许双方选择完整记录。不是另一次检索，不创建状态，也不默认加入正在运行的完整系统。

依赖选择在固定池下只能选择该池已有版本，历史包不重复加入；双方当前包都包含真实变更见证，避免撤销来源只对依赖臂开放。普通路径的历史候选也限制在实际传入版本以前。相同可访问池并不要求最终选择相同，后者才是待测读取因素。

24项依赖/证据读取检查通过（6.79秒），34项支持组/v2 runner检查通过（11.29秒）；Ruff、单文件mypy、包DAG和工具边界通过。另对关闭的continuous-v2原银行做SQLite只读备份，在两臂两故事的第1/5检查点共8个真实切片上验证版本集合一致、无未来版本进入、银行记录值不变。未访问原银行写入、未调用模型。明细见`method-architecture-fixed-history-pool-v1.json`。

当前screening-v1仍运行冻结463b5182，没有热改。该入口尚未产生受控R或2×2模型成绩，不能据离线输入公平性检查宣称协同有效。


## 同实际条件状态的2×2入口准备

新增`runners/method_architecture_factorial.py`及对应tools入口。三个声明案例覆盖例外撤销、替代供电且风扇共同前提、共享向导条件。种子从已到达的原文通过现有M条件表示局部编辑形成一次；不提供正确图、不重复生成到满意为止，不从E2最终状态手工回滚。更新原文在seed副本中只捕获一次，两条U分支拿到相同Source ID与时钟。

U0保留现有条件局部编辑，U1增加已实现的Impact区域。每个实际更新只执行一次，然后两种R读取复用该后态与同一原文/历史候选池。这个小诊断明确使用所有可见语义记录，隔离前端召回的差异；两种读取均可访问相同真实旧版本与撤销见证。R1仍需自费选择根与支持组，选择调用计入共同读取上限；R0使用原普通Evidence Pack路径。最终Reader、来源访问、模型和容量不变，关闭读后使用反馈。

配置`milai-method-architecture-factorial-v1.json`已prepare为PREPARED_ZERO_MODEL：三案例×四单元×三问题，共36读取机会，实际模型请求0。评价答案和状态义务单独预声明在`method-architecture-factorial-v1-reference.json`，执行器不加载该文件。共享seed、两条更新及四个读取单元分别计费；不能把共享诊断当成四条独立系统生命周期。

实际SQLite加模型桩验证了：seed只形成一次、U0/U1 before逐值一致、实际arrival身份相同、R0/R1版本/来源池一致、选择调用预扣一次额度、读取不改记录值、评价canary不进Writer、重读已关闭阶段不重复生成。最后相关10项通过（3.56秒）；Ruff、3文件mypy、包DAG/工具边界通过。验证矩阵首次暴露既有文件登记遗漏，补入dependency_groups与source_times，并为新测试登记正确的Foundation/External CI依赖环境；矩阵通过，未降低任何检查标准。未执行远端CI。

该入口源码需独立冻结后，在当前screening-v1队列关闭且原账本资源释放后执行。三案例结果只能作机制诊断，不能凭Y11最高就声称稳定正交互。完整W3维护时机、跨记录、W4匹配训练/增强比较、W5正常Host及独立外部评价仍待推进。


2×2实现已提交10c68e54，并以Git archive冻结为`factorial-source-v1`；冻结副本再次prepare成功、模型请求0。串行监督进程247480（exec60980）等待原screening驱动141865完成，只有双方预测/首次评分关闭且资源结清后才启动三案例。异常交接则停止，不另起账本或自动重试未知调用。队列状态与当时进程核验记录在`method-architecture-factorial-v1-queue.json`，实时状态见ignored目录`factorial-v1/queue.json`。

E2途中已观察到实际模型关系：档案室例外形成condition/modifies与exception/overrides两条边，随后撤销例外、保留一般规则；展柜初始状态形成一个AND支持组，但将原件/照片合并为一个派生结论并遗漏照片只需照度的独立规则。前者是实际机制使用，后者仍须结合后续更新判断损伤，不能把图存在直接记为关系正确或方法成功。完整筛选及首次评分仍在运行。


## W3 维护时机与真实复用成本入口

新增`runners/method_architecture_lifecycle.py`与对应tools入口，比较逐事件维护、明确变化时维护、首次查询时重建。三策略都立即保存每次到达的原文，包括被跳过语义维护的致谢/确认。明确变化策略在初始形成后，每次到达多支付一次模型判定，输入仅是本次原文和实际已存状态，不能看到后续问题。判定调用单列policy_selection成本。

查询重建在Source-only前缀的SQLite副本中从空语义状态开始；本次会话保持真实事件边界，过去会话原文按实际已打开历史材料重交付，保留原ID、角色和报告/捕获时钟。首次测试中试图把多个会话绑定为当前事件被原服务拒绝；已改走实际历史重交付接口，没有降低边界要求，也没有把旧原文重新捕获成新事件。重建任务明确要求按原始时间解释完整已到达历史，随后复用同一个Editor、schema和提交路径，生成输入没有查询或参考答案。

配置使用一条新的6事件开发流，含两次不改变规则的确认、未来生效变化、临时例外与撤回；4个检查点各执行4次实际查询。复用1次曲线取每个检查点真实首读，复用4次取全部四读；共享同一维护结果、关闭读后统计，因此不会重复生成不同状态来制造摊销差异。三策略共48个实际读取机会。维护、判定、重建、检索与读答都计入原账本；训练/Judge若另行执行则单列。字段明确为known tokens，并保留unknown usage，不能用已知部分当完整费用。

`milai-method-architecture-lifecycle-v1.json`已prepare，模型调用0，评价参考单独保存且执行器不加载。10项相关测试通过（9.35秒），覆盖每条原文保留、实际重建前态为空、过去来源身份/正文/时钟逐值不变、未来原文不进入副本、查询/评价canary不进入维护、读取不改记录值、判定成本与查询复用分账；Ruff、3文件mypy、DAG/工具边界和验证矩阵通过。测试使用模型桩，不是W3实际结果；一条开发流也不支持部署回本承诺。见`method-architecture-lifecycle-v1-checkpoint.json`。

同时E2候选预测已关闭：36事件、43答复+5已确认缺答，150次生成/801,695 tokens、embedding5,723。五次缺答均来自依赖选择的length响应；一次EDIT_SUPPORT_ROUTE_INVALID更新拒绝保留。普通臂仍在运行，尚未作双方首次评分或完整比较，不提前宣称胜负。


W3源码已提交并冻结15319207，`lifecycle-source-v1`再次prepare成功、0模型请求。串行监督进程420999（exec84404）等待原2×2监督进程247480正常关闭及完整summary；异常交接不会新派发。实时状态为`lifecycle-v1/queue.json`，当时核验记录为`method-architecture-lifecycle-v1-queue.json`。当前E2、E3、W3依次执行，分别使用463b5182、10c68e54、15319207，原连续账本保持。没有SHA校验、重开旧确认或新模型部署。


## E2 十二链首次结果与逐事件状态审查

screening-v1四阶段已正常关闭。双方从空库独立经历36事件/48QA，源码463b5182固定。首次QA：普通40 Correct、2 Omission、1 Hallucination、5 invalid；候选40 Correct、1 Omission、1 Hallucination、1 invalid、5 missing。候选缺答均为依赖选择阶段已确认length；另有4次Editor length（其中1次初始形成）、1次支持路径无效拒绝。普通有1次时间来源未选中导致的更新拒绝。所有首次结果保持，没有重判或以恢复答案替换。

| 生成tokens | 普通B1 | 候选M |
|---|---:|---:|
| Editor | 231,850 | 301,570 |
| Impact | 0 | 92,980 |
| 证据选择 | 0 | 259,676 |
| Reader | 172,067 | 147,469 |
| 预测合计 | 403,917 | 801,695 |
| 首次Judge | 131,684 | 112,326 |

候选预测生成成本增加98.5%；单看末端Reader较少，加入证据选择后并不节省。全队列325生成请求/1,449,622已知及charged tokens，207embedding请求/11,707 tokens，与原连续账本逐值一致，新增unknown0，原9/1基数保留。

同一来源作者/开发者已逐项检查两臂共48个后续事件的实际state、来源绑定和原始义务。严格UJS普通12/24、候选13/24；只计目标与非目标含义保持则18/24和14/24。按12条独立链配对bootstrap（20,000次，seed20261015），严格UJS候选减普通为4.2个百分点，95%描述区间[-25.0,+33.3]；QA Correct差为0，区间[-18.8,+20.8]。这些是开发筛选与同作者状态审查，不能作为稳定增益、非劣性或外部泛化证明。

UJS按语义、范围、时间与单位级来源归属评价，不以字符串或节点数量评分；允许明确前态和事件上的前向算术，不能从输出结果反推缺失的因果前提。初始形成缺口与后续新损伤分别记录；maps第二次是保持/准备事件，单独分层。普通方案主要问题包括复合前后时段绑定单一effective_from、钥匙保管地丢失、一般夜间规则/耳机许可丢失、初始库存日期被移到更正报告日。候选主要问题包括形成/编辑截断造成的缺失、未写入未来搬迁、存在支持组但对帘损坏返回no_change、照片独立规则漏存。双方取消讨论预约时都将复合单位旧卡状态归到只谈预约的新来源；严格来源维度保留该问题及记录层仍有旧来源的区别。

候选档案室/工作室实际形成条件与覆盖边并完成局部撤销；展柜形成一个AND支持组，更新后出现changed_premises。没有观察到已提交的显式OR支持组，替代条件主要仍以普通文本保留。

结果与逐事件标注在`method-architecture-screening-v1-summary.json`。完整问答来源审查随后已覆盖全部91个答案与5次缺答；32个答案列出时间、来源归属、推断或拒答问题，官方标签不改。状态审查与来源审查仍分开。已核对候选kiln最后负责人错答：全部3份原文包括乔原接任通知都进入候选、打开并最终驻留，模型仍回答与旧状态/旧报告一致的夏禾，说明原文混合也不保证补救错误；单次输出不能确定是语义视图还是误读原文导致。原QA标签不改。

对展柜no_change的额外CPU语法检查：合法替换在schema键序下被现有XGrammar0.2.3接受；初始示例的不同键序被默认模式拒绝，在any_order=True下接受。此处没有发现新的编辑分支不可生成问题，不能把键序限制误报为方法接口缺陷。探针0模型HTTP，原示例与结果均保留。

## E3首次关闭与冗余清理的接口修复

冻结10c68e54的三案例2×2已关闭，35/36读取有答案、1次已确认选择失败，所有读取后记录值不变。原始状态/答案和成本仍需完整审查，不预报交互收益。它暴露了两个具体拒绝：U0重复两次remove_exception，U1删除条款/条件后又remove其支持组。

已修复两种幂等清理：同一提案内已经删除的原始目标再次删除只产生一次效果；已经因目标删除而移除的支持组，允许显式清理该原始目标的组。重复操作仍验证证据和无新增正文；未知目标、为已删目标设置新组、replace/retract混用冲突仍拒绝。没有改Source/owner/visibility/CAS边界。

把两臂首次原始JSON提案原样应用到各自真实银行的独立副本：两者都成功撤销例外与条件，一般规则/外借登记逐值保持，旧版本不变。新增模型调用0，没有覆盖原始银行、重新生成答案或修改首次分数。100项相关测试通过（15.78秒），Ruff、2文件mypy、包DAG和工具边界通过。证据为`method-architecture-cancel-cleanup-replay-v1.json`。这是已观察失败的确定性重放验证，不是新的模型质量成绩。

W3继续执行冻结15319207，未热改；其实际监督进程420999、工作进程571471（exec84404）。E2/E3原句柄29617/60980已返回EXIT0。后续仍需完整E2问答来源审查、E3/W3审查、修复后的对称真实复验，以及跨记录、匹配学习、Host迁移、强/外部基线和额外模型/长历史。


随后W3监督进程于05:16:56UTC正常关闭，exec84404已返回EXIT0。三策略都有结果：逐事件15/16答复、212,042生成tokens；明确变化16/16、164,484；查询重建16/16、145,060。读取后的记录值均未改变，响应usage未新增unknown。上述仅为已关闭产物的初查，尚未完成状态/问答/判定/成本的完整对称审查，不能从更少tokens直接宣称回本或质量保持。当前三个原队列均已关闭，没有另一个模型任务在排队。


## E2/E3/W3审查补齐与后续条件

E2完整输出来源审查已覆盖91答案+5缺答，既有首次标签全部保留。另列旧Source仍在记录层但单位归属漂移、用户转述被说成作者直接确认、捕获日期被说成报告/事件日期、无依据的知识截止与拒答。invalid答案中多条核心结论与参考一致，仍不重判或计算“修正准确率”。详见screening-v1-summary的qa_source_review。

E3首轮三案例全部36次尝试已审查：35完整答复均覆盖核心参考事实，Y00/Y01/Y10/Y11分别9/9、8/9、9/9、9/9；全尝试交互量+1/9完全来自Y01一次选择器length缺答，完整答复条件下交互为0，不能视为协同证据。解释中仍有捕获时钟、间接来源当直接证据、范围混淆等问题。累计66生成/344,589 tokens、14embedding/1,571 tokens，账本一致、新unknown0。更新实际效果与原始拒绝另列于`method-architecture-factorial-v1-summary.json`。

W3全部47答案+1缺答也已读完并核对。复用1/4次的生成tokens分别为：逐事件101,123/212,042；明确变化66,730/164,484；查询重建55,847/145,060。共115生成/521,586 tokens，embedding2,739，原账本增量一致、unknown0。明确变化初始形成因无效支持路径被拒；末次判定的reason已描述明确撤销，但maintain=false，故未撤销状态。重建初次保存完整，后续却遗漏盖章/正本/封套，最后还丢失生效前徐珂；原文在所有重建请求中确实交付。原文混合仍补足多数答案，因此低token不能直接解释为质量保持或回本。逐事件策略在文本层保留了主要规则，但临时例外覆盖的复合基句包含盖章，谓词级范围还需专门验证。细节见`method-architecture-lifecycle-v1-summary.json`。

修复后对称重复使用冻结5734ade2，两个新root分别factorial-v2-r1/r2，复用v1同一真实seed与arrival，未复制HTTP、未重新生成种子、原形成成本只计一次。两次都重做双方U与R，不挑选单侧重采样。r1已EXIT0、36答案，例外撤销U0/U1都提交，另有共享条件U0支持路径拒绝；r2运行中（exec49873）。尚未完成完整语义审查，不能把提交数当成功率。

另发现固定历史池的受控入口会保留未被R1选择的旧版本，令history_revisions在该条件下不能减少交付。现已改为：两策略具有相同可访问候选，R1在决策后只交付选定旧版本；普通路径仍拥有完整候选。这是候选与最终支持组合的区分。34相关检查（12.30秒）、Ruff、单文件mypy、包DAG/工具边界通过。当前两个冻结重复不热改，明确归属全历史材料条件；完整历史选择因素仍需后续修复版实测。原始结果与成本不覆盖。


## 支持结论改写后的关系有效性

新增changed_target标记：保留节点ID但改变结论正文/角色/归属时，旧支持组不能继续把已知前提判成新结论的有效证明。它仍作为需要解释的候选保留，support_status返回unknown；不据此否定新结论。显式、来源绑定的支持组重设会解除标记。标记进入存储、Writer视图、渲染及Reader投影。

实际SQLite测试覆盖：只改结论、前提不变时旧证明变unknown；Reader/Writer都看到该状态；明确新关系后恢复supported；旧版本不变。112相关检查通过（20.37秒），Ruff、4文件mypy、包DAG/工具边界通过。另在E2展柜实际before/after上作纯投影，确认结论改写被标记、原正文与原快照不变，0模型调用/0银行写入。明细见`method-architecture-changed-target-v1.json`。当前冻结5734ade2的两个重复不包含该变更，也不包含0a9c2e4d的历史选择过滤修复；后续真实完整方法验证仍待执行。


## 最小跨记录支持切片与真实试验准备

支持组新增实际交付的外部record/unit/revision引用；目标仍属于本记录，模型只能选择已打开的短标签。引用通过原服务绑定，保存外部单位的实际来源，不复制一份无身份的外部事实。逐记录提交按显式依赖排序；后续重设可绑定同一批已经确认的前序提交，第二条失败不回滚第一条。循环保留未完成顺序，不声称跨记录原子事务。

维护候选沿实际声明的记录链接扩展；影响区域在合并的单位依赖上区分修改目标与只读前提，并保留替代支持。当前实现扫描可见记录，没有O(k)索引效率主张。Reader按选中AND/OR路径打开实际外部记录；前提已改变或撤销时同时保留绑定旧版本、当前状态及变更来源。历史读取使用当时绑定版本。未交付的外部正文不当作证据，缓存池遇到外部变化明确要求重新构造候选池。来源撤回仍通过原可见性机制传播。

147项相关测试通过（30.86秒），最新4项实际SQLite跨记录测试通过（1.42秒），10文件mypy、Ruff、包DAG/工具边界和277源文件验证矩阵通过。矩阵一次因遗漏PYTHONPATH读取安装版源码而失败，指定本工作树后通过，未改变门禁。原生XGrammar0.2.3接受no_change、新建外部支持及重设外部支持三个schema样例，0模型HTTP。这些测试不证明模型会正确形成依赖。

cross-v1已prepare零调用：两个条件化表示相同的臂、共同依赖Reader，唯一机制差别是更新是否使用影响区域；两臂独立形成，不能归因于同一before。4次来源事件要求分别保存凭证台账与入场资格，会员卡失效后保留凭条路线，二者均失效后改变资格，同时保持培训与无关蓝色柜签。每臂6题；所有状态和关系须由模型产生，未向模型提供正确图。协议记录在method-architecture-cross-v1-protocol.json。Functional Host定制提交尚未迁移支持组，本切片不表示W5完成。

原E3两个对称重复均正常关闭，仍待完整语义审查和成本核算；冻结5734ade2保持原来的全历史材料条件，不能当作修复后历史选择的效果测量。


## 两轮对称重复的完整结果

冻结5734ade2的两个重复均关闭，72个首次答案、12次更新已由同一来源作者逐项审查，不是独立评审或官方Judge分数。核心事实计数：r1的Y00/Y01/Y10/Y11分别9/8/9/9，r2为9/8/8/9，每格9题。合并18/16/17/18，每格18题。三个核心错误都在同一室内展示开放题：完整6月2日原文与正确report_time实际进入末端Reader，仍拒答开放状态，其中两次把2026捕获日期误当报告时间。其余解释中另有日期、规则归属与将用户声明升级成现场观察的问题，共24个答案登记问题，未替换原答案或标签。

更新层面，目标与保持成功U0为4/6、U1为5/6；加入来源模态后严格UJS为2/6、3/6。两轮档案室的双方均成功撤销例外，r1U1仍有孤立时间条件但没有活动豁免边。投影双方都保持电池路线与字幕独立性，但新事件单位均错误标成observed；原始seed已有相同模态问题。r1共享条件U0支持路径无效拒绝，r2双方均Editor length，无更新。全部已提交重复状态均未形成显式支持组。描述交互为r1+1/9、r2+2/9，但集中于同一错答；r2两种更新后的实际状态相同，不能据此建立依赖更新协同主张。原全历史材料条件限制仍在。

成本排除旧seed重复引用，r1新增63次生成/333,776 tokens、12次embedding/1,436；r2新增63次生成/315,349 tokens、12次embedding/1,436。合计126次生成/649,125 tokens，embedding2,872。逐阶段回执与原连续账本完全一致，新增unknown0，旧9/1基数保留。全部读取后记录值不变。完整状态、逐答标注、成本与限制见method-architecture-factorial-v2-summary.json。

跨记录8111fd8e已冻结。初次准备因live fixture路径与冻结路径不同被拒，0模型请求、账本不变；旧prepare和错误保留，执行根改为cross-v1/execution。driver1169570、exec4663串行执行control/candidate首次预测与首次评分，不重试未知请求。后续开发不改变该冻结源码。


## 跨记录首次实测关闭

8111fd8e的cross-v1/execution已于07:41:41UTC正常关闭，原exec4663返回0。双方均由模型形成两条实际记录和跨记录支持，会员卡失效后都把剩余凭条路线绑定到真实台账r2。对照初始错误地把两种凭据作为同一个AND；候选生成了OR，但把规则、培训事实与结论合成单个目标，缺少独立培训前提。这里证明外部引用/版本/逐记录机制实际运行，尚未证明模型建立完整正确的支持图。

最终撤销时，对照两条记录都提交r3，保存凭条取消与不能领取，保留培训和蓝签。候选Impact选中凭条及资格，Editor却用满8192completion tokens，JSON尚未完成，零提交，两条记录均停r2且仍有凭条有效/可领取。12个首次混合问答核心事实均覆盖，但候选最后两答依赖原文，不代表状态更新成功。首次官方标签对照6Correct，候选5Correct+1invalid；第6个Judge原样返回{}且stop，不重判。全部答案来源审查登记3个时间归属问题。

对照/候选预测生成tokens111,572/129,657；包含首次评分的整个队列47次生成/271,777 tokens、25次embedding/1,289，与原连续账本一致，新增unknown0。全部读取后记录值不变。用read-only SQLite连接经真实MemoryService读取旧版本：对照2记录共6版本，候选2记录共4版本，各4原文仍可见，0库写入。见method-architecture-cross-v1-summary.json。单条独立形成开发故事不能作因果或外部泛化结论，原失败不补跑覆盖。

## Host支持组写入路径迁移

普通Functional save/update/rewrite现在调用与Benchmark相同的EditMemory.bind_support_groups；仅关系改变也会通过原Host提交产生新版本。支持来源进入原有functional_support，旧来源保留继续受既有实际交付限制。维护commit回调增加前序真实回执参数，Host绑定同批已确认的外部版本；后续失败不回滚前序提交。B2整体重写也保存明确的新支持组，但这只是接口能力，未宣称公平性实测完成。

Host记录页交付目标所属支持组及计数，Writer从实际已交付页重建它们，缺组时不伪造完整记录；外部引用明确需要实际打开正文，不把引用当证据。新4项SQLite/普通工具测试覆盖重开、关系单独更新、B2重写、外部版本绑定、幂等与部分提交。219项不同相关测试全部通过：广测218通过/1处测试回调旧签名失败，修正该fixture后恢复测试2项通过。Ruff、3文件mypy、包DAG、工具边界、277源验证矩阵通过。未跑远端CI、未执行该新源码的真实Host模型任务；共享读取选择尚未接入，W5/E5仍未完成。见method-architecture-host-support-v1.json。


## Host共享依赖读取与真实协议

正常Functional Host新增opt-in dependency_reading，直接复用Benchmark的dependency_read_request/decode_dependency_reads和build/open/project证据包。选择原始用户请求的根节点、完整支持路线与实际历史版本，结果只含实际索引，不把gap或导航元数据当事实。调用经过原model/provider/连续账本，额外消耗当前消息一个read allowance；没有新增模型服务或独立预算。

选择请求与结果由原Store和_read回执记录，重开进程后复用成功结果；结果未知时保留原失败且不重发。选择器实际读过的来源也计入exposure。当前可见记录revision改变后重建池并计费重选，导航带pool_generation，旧索引不会悄悄指向另一条材料；旧历史读取仍按选中版本绑定外部前提。此处扫描真实可见record版本，未宣称O(k)效率。来源撤回沿原forget epoch和可见性机制处理。

4项新增SQLite测试覆盖选中的voucher+training路径、共享读取额度、重开回执复用、unknown不重派、外部更新重建池与旧索引拒绝、实际历史版本。跨记录相关8项3.94秒通过。广测532通过/3失败，发现上轮Host写入迁移在未启用cross时也传了新keyword，影响旧提交后恢复override；已仅在启用时传入，3项恢复测试10.89秒复验通过。总计535项不同相关测试通过，Ruff、3文件mypy、DAG/工具边界与277源验证矩阵通过。未作远端CI。

host-v1八条正常Host消息协议已prepare，原账本计数不变，0模型HTTP。使用已公开cross-v1开发故事从空状态开始：4次来源事件、3次纯查询以及实际初存版本查询；不提供正确初态/图，也不加载评价参考。正常队列首次尝试逐条运行，原不完整状态会保留；必要的只读恢复另列，不覆盖首次结果。模型预算保持8192输出tokens、每消息24calls、3次读取（含选择器）；源候选20、语义候选10，所有成本计入原账本。配置/fixture/protocol分别为milai-method-architecture-host-v1及method-architecture-host-v1-protocol。真实执行与语义审查尚待，W5/E5不由prepare或测试宣告完成。

冻结前最后mypy发现条件**kwargs类型推断与scope参数冲突；改为明确的启用/未启用调用分支，运行行为不变，3文件mypy及Ruff复验通过。此前535项语义/恢复检查结果保留，尚未派发Host模型请求。


## 正常Host首条失败与初始读取参数简化

冻结804d5fe2正常运行已关闭：首条FAILED、余下7条NOT_RUN。模型实际提交凭据台账r1，包含两凭据有效和蓝签；独立可变的两凭据被合并，保存组织要求又被写成凭据有效性的条件，语义质量不因提交成功而成立。共享选择器真实调用一次、正确选中3个实际单位。Host已收到完整语义正文，仍请求read_evidence([0])，省略可选pool_generation；旧实现无条件要求编号而拒绝，尽管池0尚未重建且无歧义。后续未签发Source目标再次拒绝，读取额度耗尽后的最后模型响应content=None/stop，仅有reasoning，触发VLLM_CHAT_INVALID_CONTENT。程序失败回执保留已提交状态，没有报告正常回答成功。

首次费用6生成/33,482 tokens及3embedding/256与原账本一致，新增unknown0。原失败、实际状态、末次空响应、七条未执行完整保留，见method-architecture-host-v1-first-summary.json。不能断言一个guard解释了所有模型错误，但第一次无歧义读取确实被实现拒绝。

修复为：初始池0允许省略编号；真正重建后仍要求当前generation，显式旧编号继续拒绝。25相关检查8.43秒通过，mypy/Ruff通过。后续只读恢复将使用已保存实际bank的独立副本和新查询，声明修复源码与成本，不重试首条未知/失败生成，不把恢复算首次成功。


## 只读恢复成功、后续Host答复仍失败

bef02eee冻结为host-source-v2。原bank完整复制到read-recovery-v1，保留namespace、实际版本/回执及原queue reservation，不重置连续账本。新纯查询完成：从真实语义条目回答两凭据有效、柜签蓝色，并区分2026保存时间与2034报告时间。全部record values及业务world逐值不变，maintenance和memory mutation均空。该次使用普通read_memory读取，不是对省略pool_generation路径的真实模型再验证；后者仍只有SQLite测试。恢复费用4生成/22,920 tokens、3embedding/272，账本一致、unknown新增0。原首轮成绩不改，见host-v1-recovery-summary。

随后独立恢复分支仅执行原index1：实际保存资格条目r1并引用台账r1，前序台账no_change。规则、培训和结果仍在一个复合单位，台账的两凭据也合并，故没有完整正确的OR-of-AND证明。选择器成功，但Host搜索后以持久record ID调用read_memory，未使用已签发本次q目标；读取拒绝，后一个工具因额度耗尽不可用。末次无工具模型再次content=None/stop，程序保留已提交效果并返回失败回执。此分支index2-7未运行；原首轮仍为1FAILED+7NOT_RUN。费用7生成/66,631 tokens、6embedding/425，账本一致、unknown新增0。实际模型已执行跨入口绑定和读取选择，但正常完整Host故事尚未跑通。下一步处理真实导航/答复交付，不降低修改/可见性/业务权限，也不覆盖这些失败。见host-v1-continuation-summary。

## W4配对参考扩至五组，尚未训练

新增matched-training-v2三组：跨记录凭据OR共同培训；投影两种供电OR共同风扇及用户报告模态；原件需帘+照度、照片仅需照度的不同范围。普通转换与关系目标接收完全相同的输入、修正事实、命题拆分和来源模态，关系目标额外表达支持组。共5组可审查参考，新增2个OR-of-AND、1个独立范围AND；正图均由来源作者标注，不能当成模型形成成功。

三组两种输出均通过各自实际保存的原生成schema，事实clause数组逐值相同；未修改任何实验bank、没有新模型调用或参数更新。初始展柜标签试用了不存在的时间操作数t1，schema拒绝后保留“目前”原文及来源报告时钟，没有编造事件日期。旧两组是影响/局部更新目标，新三组是形成目标，仍需规范任务特定的训练messages，独立复核标签，并在相同参数/训练token预算下做未见范围和事件顺序评价。见method-architecture-training-pairs-v2，W4尚未完成。


## Host读取目标等价解析与重复检索退出

针对真实Host把已展示record ID作为read_memory目标的断点，现仅在只读入口复用本次已经签发、当前且未撤回的导航：ID必须精确匹配该导航的record/source identity；不按猜测ID搜索，也不创建正文或修改凭据。历史专属导航不能借ID升级为当前读取，跨请求/用户与未交付ID仍拒绝。全局resolve_request_target及遗忘/修改权限路径保持严格引用要求。

Question pack且共享维护负责写入时，主Host不再暴露重复search_memory；证据包已提供候选、范围与正文读取，共享Writer自行定位更新对象。直接Writer或遗忘请求仍保留搜索。新正常Host wire测试实际经过分类→提交带支持组状态→同一依赖选择器→回答，验证选择成本经过原入口且无第二搜索目录；不将模型桩当科学结果。

11项目标/可见性测试5.54秒、25项证据/跨记录测试8.59秒、6项正常Host接线/恢复检查11.94秒通过；2文件mypy、Ruff、DAG/工具边界通过。用真实失败轨迹中的两个原始read_memory参数及其原request-target映射做read-only SQLite解析回放：都精确命中已交付记录；全局修改resolver仍拒绝raw ID，0HTTP/0库写入，也没有重置原读取额度。这只是实际参数的工程验证，不是模型恢复或改分。见method-architecture-host-read-navigation-v1.json；下一步冻结后新查询恢复并继续尚未执行的消息，旧失败保持。


## 对齐入口读取反馈开关审计

后续强对照准备发现AlignmentRun.answer没有遵守read_usage_updates=False，而基础BenchmarkRun已正确处理。只读SQLite核对旧E2：plain64条uses/16记录、candidate48条/14记录；cross双方各12条/2记录。原记录值未改的检查仍成立，但不能将它等同于完全没有读取元数据写入。四臂实际memory_ranking均dense，冻结与当前service路径只有activation模式才读取这些统计，因此此审计不提供activation模式结论。原模型输出、旧bank和首次评分不修改。

已将对齐入口条件与基础入口一致：read_usage_updates关闭或evidence_replay时不写uses。3项实际Store参数测试1.72秒、mypy/Ruff通过；新测试初次漏设functional_v1合同，补齐真实服务配置后通过，未放宽服务。旧screening/cross摘要追加审计字段，详见method-architecture-read-usage-audit-v1.json。

## Host选择阶段的有限计算修订

570b9d84恢复分支成功完成两记录读取、原index2查询以及index3会员卡失效更新；真实read_memory使用record ID已成功。原index4纯查询停止于依赖选择：原服务返回finish_reason=length、completion8192、content为空。外层通用读取回执记为read_outcome_unknown，但这次HTTP返回和计费都已确认，新增unknown usage不成立；原UNKNOWN结果保持，解释中区分此已知截断。index5-7尚未执行。

新host-v2配置仅将dependency_read阶段enable_thinking=False，其余模型、8192输出上限、3次读取额度和写入/回答阶段保持。将以实际bank副本作单独恢复和剩余消息验证；这不是原样随机重跑，也不替换原first结果或声称无偏消融收益。


## 新消息策略版本与既有调用额度

host-v2配置恢复的第一次启动在任何模型HTTP前被GENERATION_ADMISSION_STATE_INCOMPATIBLE拒绝；原连续账本generation/embedding/requests逐值未变。原因是文件级config_version把整库绑定到首个策略版本，连相同模型和额度下的新消息也不能换选择策略。没有通过删计数或换账本绕过。

现只将文件级首版本保留为历史信息；owner、bank、host参数和cap仍必须一致。每条消息自身的身份仍包含原config_version，旧消息更改版本无法恢复，也不能重新start；旧reservations/counts不改。10项额度/身份/共享上限检查2.42秒通过，正常Host两条不同版本新消息接线测试通过，旧消息改版恢复在公开Source身份边界被更早拒绝、没有新HTTP。mypy/Ruff及DAG/工具边界通过。下一步只恢复这次已确认0模型的配置启动失败，并继续原未执行index5-7；不重派旧length调用。见method-architecture-host-admission-policy-v1。

## 五个强对照的共同条件准备

按8.4准备source-only、事实追加、B1普通局部、M现有条件局部、完整新候选五臂。使用同一12条已公开E2开发链、共同原文访问/模型/Reader/首次Judge，从空状态各自形成；新候选包含跨记录支持。Source-only走现有S0只捕获路径、Unicode检索，不支付Editor或语义写入；其他臂使用原实现。新对齐代码已真正关闭读后uses写入。

五个配置均prepare成功、0模型调用，每臂36sessions/48QA。旧E2结果不混入这一新源码比较，所有五臂需在同一冻结版本重新执行。当前只准备共同8192输出上限的首个预算点，未声称完整质量—成本曲线或独立外部评价；更多资源分配点仍待。见method-architecture-strong-v1-protocol。


## Host恢复路径完成至最后、原首轮不改

a47035f6修复消息级策略版本后，只恢复了此前已确认0模型的配置启动失败。关闭dependency_read长推理、其余额度不变的分支完成恢复查询及原index5/6/7：台账r3保存卡和凭条均无效，资格r2保存不能领取，培训与蓝签保留。实际外部绑定推进到已确认台账r3。所有纯读取后record values逐值不变。四次输出核心事实正确，但图中规则/培训/结论仍合并、组织指令仍被当作有效性条件、旧规则归到复合新断言的细粒度来源问题仍存在，不能称完整正确关系图。

历史答案精确引用了实际资格r1与r2文本。真实read_evidence返回e9为historical_exact_revision1、e3为当前资格r2、e11为当前台账r3，故初存内容有实际版本正文依据。后续一个额外当前读取成功、两次额外读取因额度用尽不可用；不抹去这些拒绝。表格把版本2/3称为第二/三次更新，实际是形成后的第一/二次变更，单独登记解释问题。

对先前截断选择器与这次恢复选择器逐值比较，messages与response_schema完全相同。长推理开启时prompt4232/completion8192、length且无正文；关闭时prompt4234/completion137、stop且合法索引JSON。这只是一个事后选中的已暴露失败对、生成随机性未控制，不能当总体效应或训练收益。

该最后分支16生成/123,270 tokens、15embedding/1,595与原账本一致，新增unknown0。所有Host开发路径合计48生成/387,578 tokens、42embedding/4,068；两个0模型准备/配置失败不增加费用。原804d5fe2首轮仍1FAILED+7NOT_RUN，后续跨源码/配置恢复不得改称一个固定版本从空状态首次跑通。详见method-architecture-host-v1-recovery-v4-summary.json；新的固定版本正常Host故事仍待。

## 历史候选的导航类型修复

最后历史审阅发现，证据包正文虽标为历史版本，Host候选导航却未传递version_view，导致附加导航被当成当前read_memory。开发代码现在将真实历史标记传给既有request target投影，生成read_memory_revision；当前未显式标记的包按原契约默认为current_at_snapshot。25项证据/跨记录检查9.01秒、mypy/Ruff通过；测试验证历史目标不能用read_memory升级、精确读取仍返回初版。最初直接索引可选字段造成4项KeyError，已按现有字段默认契约修正。这不是旧答案改分，冻结运行不热改。

## 强对照执行与模型资源核对

强对照已冻结a47035f6并实际串行执行，driver1672507/exec12669。原文臂已完成36次capture-only、48答复，实际只产生48Reader响应，0Editor/Impact/embedding；首次评分尚未执行，不先判质量优劣。其余四臂继续同一队列，见strong-v1/driver.json与method-architecture-strong-v1-execution.json。

对现有78xx/79xx监听端口只做GET /v1/models：已确认的生成入口7860与7862均报告Qwen3.6-35B-A3B-FP8，另有bge-m3和reranker；其余路由失败不能据此断言具体服务类型。四张A10040GB各约39.9GB已用。没有发现可确认的另一生成族/规模，也未启动/停止服务或训练。此核对0生成调用，不满足计划的额外模型复验；见method-architecture-model-resources-v1.json。


## SimpleMem共同条件适配与原生窗口

新增SimpleMemAlignedBackend，复用已安装的官方SimpleMem text core、LanceDB、Tantivy、结构检索、规划和反思；没有另写摘要算法或原生回答器。新后端SimpleMem-native-common-reader接入现有在线/LongMemEval对齐入口，外部原生回答复现仍未完成，不把共同Reader成绩冒称作者系统成绩。

对齐输入仅包含真实已到达的role/content/timestamp，内部case/session标识不送入原生Writer，Source标签为不含评价信息的opaque标识。初稿按短会话强制flush；核对原生MemoryBuilder后改为完整窗口按原算法处理，剩余Source缓冲区在查询前process_remaining。dialogue_buffer、previous_entries、processed_count和sequence原样保存/恢复，不改变原生40窗口、2重叠或短flush不更新previous_entries的行为。问题正文不进入Writer。未确认的原生操作会阻止新操作，避免丢回执后重复flush；已完成结果直接复用。

共同条件配置增加同一份可见原文检索，原生生成条目明确标为external_memory与解释性材料，不伪造精确Source范围或把它当原文。完整原生返回、fallback、重试与操作快照均保存。原生温度/规划/反思/no-thinking保持；原生生成上限与共同模型统一为8192，实际派生policy另存。延迟flush、原生检索与共同Reader共享每问题12次生成，至少留1次Reader；原生生成/embedding和最终Reader/Judge全部使用原连续账本。原生embedding复用共同容量检查与请求记录，防止直接embed绕过请求序号而覆盖回执。原生返回顺序仅按QA20截取条数，不截断正文字符；相同Reader token容量仍适用。

109项相关检查13.48秒通过，含真实SDK/存储与MockHTTP；3个无关MERIT/MemSyCo私有资产用例未运行。新增6项验证5.60秒通过，覆盖原生窗口重开、输入隔离、已提交丢回执不重派、共享调用额度、Source/解释分离及全部原生费用回执。3文件mypy、Ruff、DAG/兼容facade、工具边界、277源验证矩阵通过。没有新服务部署、SHA校验或模型实测。

两案例pilot（projection/exhibit）6事件8QA已经prepare0调用；另备12链36事件48QA full配置。均为已公开开发数据，不能代替独立外部benchmark/长历史评价。见method-architecture-simplemem-aligned-v1-protocol。当前五臂strong仍执行冻结a47035f6，新增适配不热改队列；外部真实pilot须等其关闭后串行派发。


## 外部pilot冻结、串行交接与新完整故事准备

SimpleMem适配46bc516e已git archive冻结，官方db80b6a另建detached只读工作树，原reference工作树保持不变；没有做摘要校验。冻结配置使用冻结Lab数据与独立原生源码路径，隔离Python环境继承原运行库及已安装的Native依赖。冻结prepare成功，仍0模型调用。

外部pilot监督进程2094352/exec84597当前WAITING_FOR_STRONG。只有原strong driver1672507及所有子进程实际退出、五臂预测/首次评分全部正常关闭、末账本存在且无新增unknown/无额外插队调用时才派发6事件8QA的pilot预测和首次评分。不会自动派发12链full；需先审查pilot真实结果。见method-architecture-simplemem-aligned-v1-queue.json。当前strong前四臂均36session/48完整答复、无已知缺答，候选仍在预测；首次评分尚未做，不能预报质量胜负。

另准备全新A/B正常Host故事：5次Source事件、5次纯查询，初始一般联系人与外发本人确认、A未来生效排班、仅临时展台开放期间的对外联络例外、展台撤下后的撤销、B从一开始联系人被记错的历史纠正，并保留乌龙茶不加糖偏好。前态和关系均须由模型从空库形成；初存B内容按真实首次保存版本核查，不用纠错后的名字替代原存内容。参考义务独立存放，运行器不加载。它不同于旧17消息故事，也不是外部盲测。

host-ab-v1已prepare0HTTP，固定Host-v2预算与dependency_read无长推理设置，不做按案例分支。执行尚未开始，不宣称完整例子或W5完成。见method-architecture-host-ab-v1-protocol.json。

## 五个强对照首次结果与完整来源审阅

冻结a47035f6的五臂均于2026-10-15 12:43:02 UTC完成预测及首次评分，driver1672507已退出。每臂12条已公开开发链、36次Source到达、48个答题位置，从空状态独立形成。全部48个初始语义状态、96个后续状态及240个答题位置已由同一开发/来源作者审阅，不是独立或盲评。候选有1次选择器length导致缺答；其余239答复全部保留，未重评或筛选重跑。

| 方法 | 首次Judge Correct /48 | invalid / missing | 初始完整 /12 | 后续语义UJS确认—可能 /24 | 预测生成tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原文共同Reader | 43 | 3 / 0 | 不适用 | 不适用 | 139,661 |
| 追加事实 | 44 | 2 / 0 | 8 | 9—11 | 419,864 |
| 普通局部 | 42 | 3 / 0 | 11 | 15—16 | 410,481 |
| 现有条件局部 | 44 | 2 / 0 | 12 | 13—13 | 445,272 |
| 完整新候选 | 39 | 5 / 1 | 7 | 7—9 | 765,277 |

其余首次Judge标签逐项留在summary；来源作者的核心事实审阅依次41/46/42/48/42，来源忠实确认19/37/29/34/32，另有1/0/1/1/5份完整答复存在归属或措辞歧义。人工结果不替换Judge。UJS要求目标、非目标、时间范围和来源含义同时满足；缺少新提议记录与错误采用提议分别记录，对预约制另保留“已接受政策正确”的敏感性判断。追加臂按有日期的报告序列评价。原文臂没有语义状态，不能赋零分或虚构UJS。observed标签本身不等于独立观察，语义来源与标签风险分开；旧factorial-v2标签惩罚口径不与本表合并。歧义维度保留null及确认/可能界限。

这一个预算点没有完整候选优势：相对普通局部，预测生成tokens增加约86.4%，首次QA与保守UJS均更低。12历史簇、20,000次配对bootstrap的候选减普通局部首次QA差为−0.0625，95%百分位区间[−0.1875,0.0833]；确认UJS编码差为−0.3333，区间[−0.5833,−0.1250]。这里只描述暴露开发集一次随机运行的探索结果，不当成普适劣势、确认检验或完整成本曲线。

具体断点包括初始Editor超长/非法支持引用、后续no_change漏记新报告、覆盖复合事实时丢失非目标、来源归属和报告/捕获时钟混淆。投影案例候选文本正确仍含不充分的支持图；室内活动的规则与当前状态也曾被不当绑定。追加臂展柜末题误答“仍撕裂”，但真实Reader请求已交付完整6月3日修好原文及正确报告时间，不能解释为新来源未交付；旧语义状态同时存在，尚不能隔离哪个输入导致误答。其他QA从原文恢复正确，不补记忆状态失败。

全队列688生成响应、2,825,468生成tokens，398 embedding响应、23,740 embedding tokens，与原连续账本增量精确一致；新增unknown均0，旧9/1保留。各阶段、首次标签、逐事件回执、原文臂36次零模型capture-only及读前后record values检查见method-architecture-strong-v1-summary.json；完整逐项审阅见method-architecture-strong-v1-review.json。SimpleMem监督进程已在原队列及子进程退出后接续，12:43:04 UTC启动pilot预测，冻结46bc516e不变。

## 共用证据包区分报告与系统存储时钟

强对照完整审阅中，多臂把原文的observed_at（实际系统捕获时间）当作报告/事件日期，即使同包已有正确occurred_at/report_time。新的question-pack投影统一将原文及语义assertion中的这两种时钟呈现为reported_at/captured_at，与已有temporal字段一致；移除同一报告时钟的重复别名，并用一句字段说明区分captured_at/version_time与事件或有效期。输入原文、时间值、未知null、版本和可见性均不改，不从保存日期推测事件日期。既有存储契约、直接read_memory返回和Product API不变；这是Lab模型读取投影的字段变化。

实际SQLite参数测试覆盖早于/晚于捕获的报告及报告日期未知，经过Source捕获、真实M保存、原文与语义包读回/去重，验证相同日期、未知不补值、原库逐值不变。40项既有证据/依赖/跨记录检查通过，新3项1.79秒通过，正常Host共享读取1项2.02秒通过，合计44个不同用例。新测试初稿因遗漏I2、bound_references/source_metadata及来源assertion配置失败；补齐测试的真实写入配置后通过，未降低生产验证。Ruff、单文件mypy、DAG/兼容facade、工具依赖和277源矩阵通过。

此修订尚无实际模型质量结果，不称时钟问题已解决。Strong及正在运行的SimpleMem均使用各自原冻结源码，不热改、不重评。后续新的A/B Host从本修订冻结版本执行；既有失败与新故事分表。

## SimpleMem真实pilot收尾与完整对照排队

冻结46bc516e/native db80b6a的两案例pilot已于12:47:26 UTC完成，8份完整答复首次Judge为6Correct、2invalid，未重评。逐份作者审阅核心7/8、来源忠实6/8；两份将2026捕获时间当报告时间，展柜末题只答电子目录“不变”、未明确开放，原Judge该题仍为Correct。实际原生9条生成记忆覆盖两链主要条件与前后状态，但将报告09:00写成确切事件时间，部分timestamp丢时区、topic把插座停用称为市电outage；这类解释不冒充原文。

6次原生输入逐项等于实际已到达用户Source，问题未进入Writer，事件ID为opaque Source标识。原生先缓冲，首个查询flush前两条、下一检查点flush第三条，完整窗口40/overlap2及previous_entries行为保留；不能把查询后形成状态混成Strong的到达后UJS。8次原生检索均COMPLETED，fallback/recovered retry/admission rejection均空，原生flush+检索+Reader每题6或5调用，低于共同12上限。全部52生成响应/74,620 tokens、32embedding/1,003 tokens，与连续账本精确一致，新增unknown0。预测生成52,790 tokens，36原生core调用23,884、8Reader28,906；8首次Judge21,830另计。见simplemem-pilot-v1-summary。

新A/B Host冻结b33d5690、独立空库，于12:48:20 UTC接续；driver2384059/exec41638。全10消息第一尝试，不用先前修复分支冒充首轮。当前已完成初存、初次查询、未来A更新及查询，最终质量仍待完整状态/历史审阅。见host-ab-v1-execution。

SimpleMem完整12链36事件48QA已冻结prepare0HTTP，并排队等待本Host lane及子进程退出、完整末账本/无新增unknown/无插队调用后再运行。监督driver2400057/exec62427，暂WAITING_FOR_AB_HOST。沿用46bc516e以保持与Strong的共同Reader条件，不混入新时钟投影；两条pilot链在新空库完整cohort中重新生成，pilot保留且不与full合并。仍是公开开发数据，不满足独立外部benchmark/长历史/额外模型要求。见simplemem-full-v1-execution。

## 新A/B首轮在已提交撤销后遇到目录封装超限

host-ab-v1第一轮关闭为6COMPLETED、1FAILED、3NOT_RUN。初存r1保存A林舒/B沈瑜、外发本人确认及茶偏好；r2保存A从6月15日起陈丹及原林舒；r3追加6月12日展台开放期间对外联络曾蕊；r4实际撤去临时条款，未来安排/确认/B/偏好均保留。前三个纯查询完整回答，读后record values逐值不变；全部版本没有relation/support group，范围在独立正文与时钟中表达，不能当关系形成成功。

index6分类返回allow_forgetting=True，因而使用常规resident/目录路径；没有实际forget操作。共享维护已提交r4，随后read_memory成功交付当前6个单位，下一pre_model_hook因V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT停止，未交付最终答复。index7撤销后查询、index8 B纠错及index9历史查询未运行。28生成响应182,422 tokens、27embedding2,483，与原账本精确一致，新增unknown0。见host-ab-v1-first-summary。仍未满足完整成功故事；不把真实提交当完整答复，也不把首次失败改成恢复成功。

在实际失败SQLite的独立backup副本上、相同tokenizer/8192材料限制、既有binding/读回执重放model_material，0HTTP复现：正文先取3个单位8120tokens，但后加目录最低封装已8211，目录显式省略回执又达8357。问题是正文分页没有预留目录最低开销。现预先计入空目录及真实后续cursor，再按现有优先级分页正文和导航；不增加预算、切正文字符串或删除历史。实际副本重放返回2个正文单位、1个导航项，共7910tokens，其余正文保留pending及continuations。原实验库不改、尚未做模型恢复。

新增3项实际Store分页检查覆盖三个固定材料容量；连同当前/历史resident切换、重开、显式比较保留、未完成维护及真实Host hook等9个用例通过（4项4.08秒、5项5.65秒），Ruff/单文件mypy/DAG通过。下一次用修复冻结版本、实际库副本继续原未执行7–9，不重派原index6；首轮和后续结果分开。SimpleMem完整队列已在首轮关闭后接续，driver2400057/exec62427，预测child2406918，当前仍运行冻结46bc516e。
