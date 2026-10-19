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
| M1/D1/E0：6 历史×2目的×规则/Laya=24 次原生外部调用 | 原 Host 请求、内部 trace、返回、答案、首次失败和成本 | 六历史均已准备；首历史JSON诊断完成，原生0/24 |
| query-only、丰富请求、跨调用引用和模型反馈 | 接口测试＋实际轨迹 | 机械通过；已有JSON开发轨迹，未完成全量语义验收 |
| 六种条件配对＋D2 参数化补搜/范围 | 同池目的、时间、已读、相关/无关更新、排除范围、预算两侧效果 | 未完成；参数化 SEARCH 已接入，但六类语义配对未验证 |
| FollowIR / 合法 MemOps train / MuSiQue-Full TRAIN | 来源/许可版本、主题背景共享种子分组、实际 Store 状态与偏好 | FollowIR已导入分组；T0的64train/16dev只完成来源登记，轨迹标签未编译 |
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

当前 7860 服务未启用 tool parser；第二次派发证实连命名原生工具调用也需要该配置。E0 的设计仍为原生工具调用，
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

## 首次原生派发失败与适配修订

冻结源码 `bbf27e2b` 的 `runs/e0-first-history-v1` 在第一个规则位置进入原 Host，
但聊天桥在 HTTP 前拒绝命名 tool_choice，错误 `NATIVE_CHAT_PROTOCOL_UNSUPPORTED`。
驱动已终止；1个失败位置保留，3个位置未开始。generation_requests、生成/embedding
用量和 unknown_usage 增量均为0。没有把这次失败替换成成功或自动重试。

修订只允许命名选择当前实际目录中的函数，仍保留未知名称、required限制和
response_format边界。正常Host测试显式发出命名选择，修改前重现失败，修改后通过。
新用例/Provider检查23通过；一个旧 `json_zero_tools` manual golden 不匹配，
已在未修改 Provider 的冻结 bbf27e2b 上重现同一项失败，属于已有差异；未刷新 golden。两模块 mypy 和包边界通过。

## 服务原生能力与新的开发版本

`runs/e0-first-history-v2` 使用冻结 `0f59b4f2`。启动时 source-version 参数是人类标签
`native-v2-local-commit`，冻结目录的 source-identity.json 明确映射实际提交；未改运行输入。
服务对命名调用返回 HTTP400：`tool_choice=function ... requires --tool-call-parser to be set`。
驱动终止，第一失败保留，其余3位置未运行。原账本增量1请求、13,714 charged tokens、
0 known tokens、1 unknown usage；保持保守收费和原计数，不重置或推算为零。

本地已安装 qwen3_xml；在原容器里用实际 tokenizer 对合成 XML 调用离线解析，正确得到
query 和嵌套 read_goal，零模型前向。配置候选保存在 ignored 的
`artifacts/host-intent-retrieval-v3/existing-host-native-change.json`。需要按原资源配置
重建并重启共享7860容器，仅增加 `--enable-auto-tool-choice --tool-call-parser qwen3_xml`，
保留旧容器回滚。已向用户请求这项共享服务中断的许可；未执行。等待回复不视为同意。

第二次真实派发的输入另暴露了旧 Host 的 Writer prelude：当 save/update 仍在目录中时，
`for_write` 会先给出原文。这不是工具取证成功。新的检索 profile 只暴露 milai_retrieve，
原保存/更正/遗忘仍在原 FunctionalEditMemory profile 中。加强的正常 Host 回归现已断言
第一次模型输入没有历史答案，材料只能从实际工具回执进入下一次模型调用。

新开发版本还接入同一 EvidenceOperations 中的参数化 SEARCH：8/16 两档，最多两次，
候选目标来自原 query、Host required_points 或已打开文本；补搜合并实际发现项并保留原索引。
不再把完整 source_scope 无条件塞进候选池，不生成离线答案条件，也没有另加查询生成模型。
实际 SQLite 回归显示第二个请求要点能够发现首次池外来源。小至两文档的 BM25 IDF 会出现
零分并列，这是继承检索器的性质；该机械定位样例使用三文档验证明确非零排序，不修改检索算法。
这仍未证明六类条件配对中的语义有效性。

新的7项检索测试通过；先前受影响控制/视图测试与静态检查保持单列记录。
原生验收仍为0/24成功调用。计划先以同一工具的现有 JSON-action 传输作功能诊断，
不把它计入 E0 原生验收，也不伪称 M1 完成。后续仍需完整六历史、训练、因素/外部矩阵。

## 第一历史 JSON-action 诊断已关闭

冻结 `ec9d4ef7`，`runs/first-history-json-v3`，驱动81.979秒关闭4/4任务。
逐条对照实际 user 原文：规则2/2、Laya2/2最终任务正确。两个原话任务引用完整原文，
两个应用任务正确区分晨会 Spanish、周报 English。只有1个作者开发背景，不支持泛化或优越性结论。
四个实际首轮 HTTP 输入均未包含 Spanish 或原来源正文，证据经工具返回后才进入 Host。

实际8次检索调用尝试：2次schema拒绝、6次执行、其中2次空返回。
Laya应用任务在候选已经可读时两次提前返回空材料，Host随后继续请求，第三次才读取来源。
这属于原轨迹内的真实续取，不是重新采样任务；不把最终正确抹去中途失败和额外开销。
规则两任务均先重复原query的8/16搜索，再读原文并刷新；Laya原话任务还以已读文本补搜。
三个实际视图共5个节点、0条关系规则，节点均能对应原文；规则原话视图有不必要的
“未单独隔离原句”不确定性，但原文同时返回，最终引用仍正确。

| 阶段 | HTTP请求数 | 生成总tokens | HTTP秒（与工具内计时嵌套，不重复相加） |
|---|---:|---:|---:|
| Host请求，包括2次格式错误 | 8 | 18,888 | 33.712 |
| 视图生成 | 3 | 3,909 | 4.850 |
| Host最终回答 | 4 | 10,327 | 8.349 |
| 合计 | 15 | 33,124 | 46.911 |

生成known/charged增量均33,124，新增unknown=0，embedding=0。
Laya两条消息共实际加载1次（6.523秒），13次前向、12,651输入tokens（16.386秒），
不是每消息重载，也不把本地决策次数算作生成HTTP次数。三项生成stage tokens与关闭账本增量完全一致。
旧原生400失败的13,714 charged/+1unknown单独保留；不与本轮实际known tokens混为已知用量。
结果索引：`data/manifests/host-intent-retrieval-v3-first-history-results.json`。
报告组装CPU记录待原账本结算；未测人工阅读/标注时间不写零。

依据首次结果修订下一开发版本（尚未用于新模型运行）：
可选 target_scope 接受自然语言、对象或null，保留其原意，不作为授权字段。
原有合法evidence类别不扩充为题目特例，首次自造 user_preferences 仍是无效类别。
QA配置明确将业务工具目录设为空；实际Host曾因无关的预约工具目录新增item key之类取证要求。
该设置只收窄此实验可用工具，原Host默认业务目录不变。正常Host的8项机械测试通过，
覆盖两种实际scope错误形态、首轮无来源泄漏与唯一检索目录。未用重跑成功替换v3的原失败。

下一项仍是补齐六历史：生效前后、真实保存版本、已取得部分证据、同名作用域、
缺失证据/旧视图。真实存储历史要通过原save/update操作形成，不能写伪历史JSON冒充版本。
需要部分证据的任务必须使用实际前次返回的引用；任何额外调用和setup成本单列。
原生服务变更仍等待用户答复，原生E0为0/24。M1–M6、训练和外部矩阵都未完成，目标保持active。

## 六历史准备与第二批诊断

`data/fixtures/host-intent-retrieval-v3-e0.json` 现包含完整六个作者开发背景，每个两种请求。
第一历史的旧 JSON 首次结果不重跑；第二批只运行新增五历史×2请求×2策略=20个任务位置。
所有背景仍为 dev，不进入训练或未见确认。

`runners/retrieval_histories.py` 仅作评测侧准备：复用原 seed_sources、MemoryService、
FunctionalEditMemory.save_edit/update_edit 和 IntentRetrievalMemory.retrieve，不写伪版本JSON。
保存历史用例明确是人为声明的 Writer 错误夹具：原话April3，真实提交rev1=April8，
真实修订rev2=April6。不是新模型产生的Writer错误，也不是把某次评价状态改成理想结果。

部分证据用例的两条件都执行相同的 Fixed(reads=1)、3步预读，形成真实快照引用。
只给 with_prior 条件展示自己的实际回执。该回执经真实 tokenizer/Store 检查仅含N-214房间，
不含7316门禁码；两个条件的初始来源和预读Store状态一致。脚本预读不计入Host评价调用，
但原始回执、步骤和CPU/时间单列保留。不存在跨策略赠送优质视图。

变更视图用例让同一策略的两次请求使用同一bank；第二次才捕获生效变更。
只观察各策略实际形成的视图，未形成视图的轨迹不能宣称检验了过期复用。
其他目的配对各用独立bank，初始原来源相同。评测侧review_basis和另一请求不进入Host输入。

六历史使用主配置完成实际离线准备，0模型调用，见
`artifacts/host-intent-retrieval-v3/six-history-preflight-v1/summary.json`。
两项真实SQLite准备回归通过；正常工具回归一起10项通过后才冻结运行。
原生服务授权仍待答复；第二批明确为JSON-action开发诊断，不冒充24次原生验收。

## 新增五历史的20个首次位置全部关闭

方法冻结 `c2fc3928`。主进程在第14位置（规则/South）发生已知长度失败并退出；
确认进程消失、响应finish_reason=length、未知用量未增加后，仅继续六个未启动位置。
两个后续运行分别关闭2个同名作用域Laya位置、4个连续变更位置。没有重跑任一闭合位置。
三个驱动的原terminal状态分别FAILED/FAILED/COMPLETED，不能因为合并审阅而改写成全成功。

| 策略 | 完整正确 | 未完成取证 | 证据类别错误 | 长度失败 | schema失败 |
|---|---:|---:|---:|---:|---:|
| rules | 9 | 0 | 0 | 1 | 0 |
| 旧Laya warm-start | 4 | 4 | 1 | 0 | 1 |

以上每法10位置、5个开发背景。规则真实读取了数据库revision1的April8，区别于原话April3；
Laya在“实际首次保存”任务中读取原文上下文后回答April3，是证据类别错误。
另外四个Laya任务未取回库内存在的必要材料；这不表示删除成功或原事实丢失。
所有20份实际Source清单都保留了声明的初始正文及适用的新到来源，已逐项比对正文。
规则South的9464已知tokens长度失败发生于第一次Host生成，尚无工具调用；
LayaSouth在一条Host响应里提出两个read_goal带额外语义字段的调用，两者被拒绝后耗尽原格式额度。

实际工具尝试rules11/Laya15，执行10/12，空返回1/6；一例规则空返回由Host请求仅2步造成，
随后Host在共享额度内继续。Laya既有搜索前空返回，也有1–3个可读候选仍空返回。
部分证据两臂均实际传递已发出的known_evidence_refs：规则普通READ从4变3但增加1次引用重开，
不能据此宣称净成本节省；Laya从直接生成视图变为SEARCH+两次READ，两个最终回答都正确。

20个查询均无语义写入、遗忘或业务操作；真实保存夹具在查询前独立执行8次脚本save/update。
四个实际prefetch准备读取也单列，不冒充Host评价调用。计时和原始回执保留在各bank的
retrieval-setup.json，研究侧预备工作不写成免费。

三个关闭账本增量共54次生成HTTP、134912 known/charged tokens、新增unknown=0、embedding=0。
阶段tokens：Host请求50323、视图18144、完成回答56981、未完成Host响应9464，和账本完全一致。
Laya29次前向、41797输入tokens、66.481秒，因分成三个进程实际加载3次、15.962秒。
三段端到端时钟分别311.778/70.394/70.072秒；不要把内嵌HTTP/前向/工具wall再加到端到端上。
规则生成73964 tokens，Laya60948，但后者只完成4/10；较少用量不是质量保持的效率优势。

10个实际交付视图共38节点、0规则，逐视图审阅保存在
`data/manifests/host-intent-retrieval-v3-remaining-state-review.json`。
原文事实通常有依据，但保存历史视图并不包含真实rev1；部分视图还保留预读问题作为reported节点，
连续变更视图保留旧500及派生assistant复述，不能把这些图一概认证为当前真相。
本批实际USE_VIEW=0；规则在新到800来源后刷新自己的revision2，Laya没有先前视图可供复用。
因此仍没有“所有策略正确处理旧视图复用”的证据。

首历史4位置来自较早ec9d4ef7配置；可以登记六历史共24个JSON诊断位置已关闭，
但不能把混合版本结果当作完整同冻结版本实验，更不是24次原生外部调用验收。
结果与独立于程序的作者审阅分别为
`host-intent-retrieval-v3-remaining-results.json`、`host-intent-retrieval-v3-remaining-author-review.json`。

## 下一版本接口简化与训练来源进展

实际格式失败显示，Host会把范围放在read_goal，或把目的/要点放在task_context。
这类语义信息现在原样保留，不新增域词典、别名路由或逐个错误特判。
read_goal/task_context允许额外语义字段，既有引用结构、资源上限、身份和权限路径未改变；
未知evidence类别仍不伪装成已实现的读取能力。冻结c2fc3928对同一增强测试重现extra_forbidden，
当前实现通过。11项工具/真实准备/分组回归通过，静态检查与依赖边界继续验证。
该修订尚未用于重跑旧位置，不能把机械通过记成新模型质量改善。

已从[官方FollowIR-train](https://huggingface.co/datasets/jhu-clsp/FollowIR-train)下载原train.jsonl，
实际1776行、878true/898false、1277原TREC id、1209原query字符串。
按原id、忽略大小写/空白差异的重复query及完全相同document形成连通分组，得到1206组；
seed0的80/20分配为train965组1427行、dev241组349行，没有跨组展开后再拆分。
492组兼有两类标签，356组仅true、358组仅false，不能假设每组都有正负对。
分组不使用label决定分配，也没有SHA/替代内容指纹。
[官方数据卡](https://huggingface.co/datasets/jhu-clsp/FollowIR-train/raw/main/README.md)声明Apache-2.0，
说明document为合成后筛选材料；教师score不是真实正确概率。这里只完成来源/分组，不是操作轨迹或训练。
精简来源记录在 `host-intent-retrieval-v3-followir-intake.json`，大文件保持ignored。

T0来源登记已固定64train/16dev：57个既有合法MemOps source_task训练背景＋7个既有已准入MuSiQue训练组；
开发为8个MemOps、6个本轮作者历史、2个MuSiQue组。继承最保护的划分，排除原冲突背景和MuSiQue
reference-boundary冲突，不读新保留集正文。MuSiQue7组按既有metadata选择2个三跳、5个两跳，
未按当前模型结果换题；已有共享背景限制保留，不宣称彻底的预训练/全文隔离。
登记文件 `host-intent-retrieval-v3-t0-allocation.json`，目前没有v3训练权重。

下一项是从这些合法train来源生成实际Host请求与工具状态，覆盖query-only/丰富请求、
互补读取、真实保存版本、视图与变化条件，再进行来源审阅和普通CE。
旧的source-only偏好不能直接冒充本版监督；FollowIR适用性也不能直接变成HANDOFF标签。
完整native E0、M2六类配对、T0/T1/T2、多种子、因素消融及三类外部评价仍未完成。
