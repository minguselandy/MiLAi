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
