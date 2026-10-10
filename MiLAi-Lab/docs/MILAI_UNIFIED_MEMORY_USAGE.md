# 统一记忆功能候选与当前执行状态

当前按用户提供的[全局修复与功能优先规划](MILAI_GLOBAL_REPAIR_AND_FUNCTION_FIRST_PLAN_20261009.md)
执行，集成分支为 `feat/lab-global-function-first-20261009`。第一版源码 `bbe77e9`
的真实 Host20 已闭合；历史修复候选 `milai-global-function-first-v2` 冻结源码为 `1cfb400`。
当前选择 `milai-global-function-first-v3`，冻结源码为`5019968`。
2026-10-09 23:12:49 UTC从空库开始复验原Host20，23:33:00 UTC已闭合并对账；
输出`artifacts/global-function-first/host20-5019968-v3`，runtime为`host20-5019968-runtime-v3`。
同版五方法完整预测已调度，实际PID1854770，输出`five-dev277-5019968-v3`，
配置`five-dev277-5019968-v3-prepared/config.json`，runtime为`five-dev277-5019968-runtime-v3`。
按B0/B1/B2/M/Append-only串行，各277会话/705QA/595更新，合计1385/3525/2975；
各方法/用户新空库，旧前缀不拼接，全部预测保存后再单独统一评分。
运行时看最新PID与原生execution终态，本文RUNNING只描述这个固定时点。
2026-10-10 00:12:36 UTC固定观察为B0已保存13会话/35逐题检查点、已知缺答0，其他四方法尚未开始；
进程匹配、推理租约持有。真实预测/评分与后续阶段仍未闭合，不能据此比较方法质量。
原Host20新空库运行在2026-10-09 17:56:46 UTC停止：13 COMPLETED、7 NOT_RUN。
两次遗忘拒绝回执缺少effect字段，汇总保守标成unknown；独立代码边界及只读数据库核对
确认仅这两次属于写入前无效果拒绝，原STOPPED结果保持原样。18:04:32 UTC启动单独补充运行，
仅处理尚未尝试的7条新输入，仍使用同一冻结源码，已于18:11:41 UTC闭合：5 COMPLETED、2 FAILED。
原20条输入各尝试一次，分段总计18 COMPLETED、2 FAILED。四用户前缀M于18:14 UTC启动，
19:19 UTC已核对预测闭合：32/32会话、73/73回答、72原生更新机会，无已知只读缺答。
源码仍为`1cfb400`，输出`artifacts/global-function-first/prefix8-1cfb400-v2/M`；
原Judge评分进程在最后会话中消失，22:38 UTC核验为31/32会话已评分；
655份Judge响应均stop，第656请求有请求/账本预留、无响应，原终态缺失，不能标成完成。
22:42 UTC单独启动评分补充，只发送从未尝试的657—677项，22:47 UTC已闭合并对账；
第656项保留invalid/unconfirmed，不重试、不猜标签，原中断输出和费用完整保留。
补充目录为`artifacts/global-function-first/prefix8-1cfb400-v2-score-supplement/M`，
同一冻结源码/配置，重用全部原预测和31份已完成评价，不重做Writer、Reader或embedding。
实际结果位于 ignored `artifacts/global-function-first/host20-1cfb400-v2`，原运行与补充运行
各自保留execution/results/accounting；调度前核对实际终态与PID。
旧失败、费用和历次运行观察完整保留在[历史状态页](MILAI_UNIFIED_MEMORY_USAGE_HISTORY_THROUGH_20261009.md)，
其中“RUNNING”均为原时点快照，不作为当前进程状态。

## 当前实现与入口

当前一个配置文件 `configs/milai-global-function-first.json` 提供 functional 和 benchmark
两个入口。Host 维持原 JSON v9 当前请求、staged/record、8192 输出、24 次消息调用额度；
benchmark 维持 staged/record_units、K10、65536 上下文、32768 输出、512 余量；
v3只将benchmark Editor thinking开启，Host Editor仍关闭。两入口其他阶段配置不变。
两入口共用既有 Qwen3.6/BGE 服务和原连续账本，保持各自原来的读取权限。

- `memory/reader_projection.py` 是纯投影。实际单元替代整版正文必须有精确渲染证明；
  不可证明时保留正文。重复完整元数据共用一张单层表，不推断缺失信息或继承默认值。
  benchmark 的原 `revision_evidence` 正文和范围仍直接交付；Host 保持原文和历史工具。
- 完整请求容量使用部署的真实 Qwen 模板和阶段 thinking。逐条成本只作提示，
  联合容量另算。超限保留全部所选引用、未交付状态及整事项页面计划；
  benchmark 当前不执行该页面计划，已知 HTTP 前超限记录缺答后继续自然历史。
- 已确认 CURRENT 业务 schema 或 length 失败且用量已知时，只有独立明确的当前保存范围才继续记忆工作，
  业务分支不取得执行许可。纯保存恢复不发现或重办业务；当前只读不继承旧写权限。
- 完成信息累积实际保存回执，每个已返回批次立即进入 trace；原文捕获、语义提交、
  未完成业务和遗忘分项表达。原始模型答案与程序附加反馈分别保存。
- Extractor/Editor 保留考虑、愿望、计划、说话者与主体；候选仅作线索，Source 才是依据。
  既有引用 keep、原文 Episode 和局部算子继续复用。

正常使用入口示例（从 MiLAi-Lab 执行；使用已安装的Lab环境）：

```bash
MILAI_PYTHON=/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python
PYTHONPATH=src "$MILAI_PYTHON" tools/run_functional.py \
  --runtime-dir artifacts/global-function-first/personal-runtime prepare \
  --config configs/milai-global-function-first.json \
  --root artifacts/global-function-first/personal
PYTHONPATH=src "$MILAI_PYTHON" tools/run_functional.py \
  --runtime-dir artifacts/global-function-first/personal-runtime message \
  --root artifacts/global-function-first/personal --bank personal --owner example \
  --session example --message-id save-1 --text '请记住，我的午休提醒用静音模式。'
```

解释器路径可替换为已安装Lab依赖的环境。runtime目录在导入SQLite等模块前设定；
当前机器的系统`python`不可用、默认临时盘已满，工作树复用原checkout的`.venv`。
prepare只准备；message是真实功能调用，会使用现有服务和账本。原实验配置与
默认 fail-fast 保持兼容，不把旧请求重新解释成新策略。

## 已闭合验证与旧实验

原失败八事项经实际 Qwen thinking 模板、原问题和 read_goal 独立复算：
**32446 → 30520 input tokens，限额仍为 32256**。8/8 有整版渲染证明，
56 个单元、39 段原证据正文/范围、14 项正条件及562项时间字段通过还原核对。
该材料检查为 0 HTTP。另在第一版冻结源码上执行一次真实只读 Reader：
正式 stop，实际输入30520，输出2166（含thinking），合计32686 known/charged；
0 embedding、0 Judge、新unknown0。原始模型答案已保存，语义正确性尚未统一评分。

第一版原三链20消息在2026-10-09 17:19:01 UTC闭合，20/20实际尝试，
17 COMPLETED / 3 FAILED。逐响应核对为99 generation / 784557 known=charged，
35 embedding / 1532 tokens；stop53、tool_calls44、length2，新unknown0，Judge0。
fixture/control不变，每个新消息单独CLI进程；失败消息未重试，旧运行未热改。

| 原链 | 结构完成 | 真实断点与范围 |
|---|---:|---|
| 保存、切换、重开6消息 | 6/6 | 两项实际保存，后续只读无语义或业务写入；不据此推出完整语义验收 |
| 更正、历史、遗忘8消息 | 6/8 | 两次确认length；Editor首次补造起效日期、漏改明确通知值；Reader错误继承未规定分组频率、误解查询缺失 |
| 业务、结果保存、遗忘6消息 | 5/6 | 首请求在多余旧请求解析阶段schema失败、尚无业务效果；故未验证原本的部分业务续办链。后续确实撤销8个来源可见性 |

更正链当前读第一页实际送4/5单元，第5加入后约8922>8192；首单元已送达，
历史17项确为三个版本5+7+5语义单元。共用元数据补丁的完整当前页为6593/6587，
历史首版完整5单元为6027/6020，均包含表及说明；历史仍需分页。零HTTP还原检查保持所有字段，
不改变页额度、正文、范围、实际选择器或原文权限。
当前补丁还处理已知截断的独立保存、无issued旧请求时的确定空选择，以及真实保存回执反馈。
Source提示将明确值与实际状态比对，未知起效日期保持未知。第二版前13条实际调用为
71 generation / 565201 known=charged、1246 embedding tokens、新unknown0、Judge0。
补充段另31 generation / 336871 known=charged、610 embedding tokens。合计逐响应核对为
102 generation / 902072 known=charged、50 embedding / 1856 tokens；stop61、tool_calls39、length2，
新增unknown0、Judge0，原停止和补充终态分别保留。更正链首次仍补造季度日期并被拒绝；
后续明确通知值实际提交，但Reader仍把整体频率
错误赋给未单独规定的分组。有效遗忘实际撤销一个事项及9个来源；未形成事项的初始Source
仍可见，不能据此宣称全部关联原话已遗忘。补充链已实际形成一次部分预订和一次单独补标签，
只有一份预订、两次业务尝试；其纯保存请求却被CURRENT误解成业务续办，未取得保存许可。
业务遗忘在已确认length前提交r3语义撤销，未调用forget_memory或撤销可见性；原话/历史仍可读。
重开模型把retracted误报成已清除，不能算成功遗忘。上述普通语义
失败保留，不以COMPLETED冒充验收。原始答案和附加回执分存；前表费用仍仅描述第一版。

旧 M36 (`36b0401`) 仍为 FAILED：21 个完整会话预测/46 答案，末会话另有2个实际响应，
qa2 在 HTTP 前因32446输入终止。22份维护结果中17 completed/5 incomplete，
43去重提交、6 current_boundary_source_required 拒绝。旧数据不补成新候选轨迹。
旧闭合成本为162生成/1748782 known tokens、140 encoder/18648 tokens，新增unknown0。
原全局账本固定闭合值49574请求/227101922 known/227378618 charged、2042879 embedding，
历史 generation unknown6；不重置或把后续实时账本差额误记成旧 M 成本。

第一版集成后29项受影响正常 SQLite/模拟 HTTP 检查通过；受影响文件 Ruff、严格类型检查
及 package/tools 依赖边界通过。检查记录在本地 ignored 验证产物中保存。
模拟调用不计真实模型样本，也不宣称完整仓库或远端 Full 通过。
第二版请求修复19项检查、合流后的共同投影及正常Host10项检查通过（包含重叠复查）；
三项新Reader检查与Source开发者12项既有检查另有闭合记录。六个受影响源码严格类型、
Ruff、依赖边界及旧八事项真实模板复算通过。没有把重复检查累加为新样本。
开发分支另合入`e41787a`：仅两处已知写入前遗忘拒绝返回effect=none，验证及异常路径不变。
开发者5项窄检查和Root合流后1项真实SQLite检查通过（重叠）；写入后回执丢失仍为unconfirmed，
裸旧rejected回执仍为unknown。该补丁未进入冻结`1cfb400`，不改写实验身份或历史结果。
开发分支又合入`0d297ad`：仅澄清既有CURRENT提示，纯补存仍是记忆续办，查询/跳过已存
是执行限制，禁止应用动作时业务为空；纯遗忘不额外要求新语义保存。schema与授权程序未改。
16项既有mock/SQLite检查、Ruff/类型通过；Root合流后复查1项纯保存恢复通过（重叠）。
合流时实际模型语义尚未复验；历史`1cfb400`对照不含该补丁，v3已纳入上述两个工程修复，
其实际结果见下段。

v3原三链Host20实际全部尝试、20 COMPLETED，仅表示结构结束。122生成/1666232 known=charged、
63 embedding/3571 tokens；61stop、61tool_calls、无length，新增unknown0、Judge0。
原20逐消息用量、20完整trace与固定账本逐项相符；Root已阅读正式答案并核对实际回执。
纯保存续办正确取得continue_prior保存范围、业务写权限为false，实际提交r3并确认原请求结果保存；
始终一份预订/两次业务尝试，标签从失败变为created，后续保存/只读/遗忘未增加业务效果。
更正链纯遗忘没有新语义保存；三次已知无效果拒绝、两次实际可见性撤销，重开未返回被撤销正文。
业务纯遗忘虽声明正确，却十次选择无效/未发出的引用，零撤销，事项及历史仍可见；不能算通过。
其他失败包括：整体频率继承到未规定分区，旧“南北均无单独次数”未随新增北区规则更正，
历史只读10/24项漏撤销前两天通知阶段，答错当前版本号，把查询found当预订状态；
一次只读实际业务查询只读了记忆/来源，没有新应用查询。原模型答案与程序反馈分别保存。
结果及限定判断见本地`root-semantic-observations.json`和`closed-response-reconciliation.json`，
不把费用/结构核对当语义认证；普通语义失败按规划11.1保留并继续主实验。

## 下一项工作与仍未完成范围

原三链20输入及两段成本已核对，实际限制、原恢复control与失败均保留。四用户前缀预测已闭合，
逐响应与固定账本核对为237生成/2159360 known=charged、214 embedding/36847tokens；
237响应均stop，Reader峰值输入28778，新unknown0，原历史unknown6/0不变。
32份维护结果为23 completed/9 incomplete，82去重实际提交、12拒绝，普通语义失败保留。
全部32会话/73回答及逐题检查点先保存，另备份完整aggregate。原评分中断固定差额为
656生成请求/2716058 known/2763437 charged tokens、0 embedding，新增unknown1。
其中655已保存响应用量完全对应known；未知第656项保留47379预留tokens，原历史unknown6
因此成为7。服务运行/排队均0，日志没有可恢复答案或精确用量，不据此改写unknown。
单独评分补充21生成/96531 known=charged、21stop、新unknown0、0 embedding；
起点等于原中断固定账本，全部32预测/73答案与评分前备份相同，原检查点未变。
合计Judge实际677请求、676保存响应、2812589 known/2859968 charged、新unknown1；
原中断不因补充完成改成原生COMPLETED，未知项没有重试。

统一结果为QA **44/73 Correct（有效71）**、更新 **48/72 Correct（有效67）**。
QA另19 Hallucination、8 Omission、2 invalid；更新另19 Omission、2原标签Omitted和3空标签，
后两种均保留invalid，不改写成Omission。540原生记忆点分成468形成/72更新记录，
另82准确性记录；作者形成主分母439另排除29 interference，不能用439替代原540机会。
同家族Judge和开发者来源核查不是独立确认。一处实际用户原话收入为18000，而参考答案为20000；
Reader按原话回答被作者Judge判Hallucination。保留原标签，同时单列参考/来源冲突，
不以gold纠正Source。Editor此前把同一用户证据改为20000仍是另一项来源忠实性错误。
预先固定7个已完成来源切片的thinking单变量对照已于23:01 UTC核对闭合，
每设置各两次、28提案全部保留：28gen/527243 known=charged、28stop、新unknown0、0emb/0Judge。
False14份220425 known/6683 output，True14份306818 known/93104 output；
True峰值输出9747，4份超过Host8192额度，不能直接据此变更Host模式。
输出`artifacts/global-function-first/editor-thinking-1cfb400-matched-v1`，来源审查已闭合28/28。
不运行Store或提交，不把28/28 wire schema合法当正式编译通过，不自动选最好答案或采用配置。
工程错误与普通语义失败分别定位；unknown HTTP、未知写入/业务效果和 Store 故障停止相关路径，
不盲重试。新 benchmark 预先声明按题保存成功及已知只读缺答，缺答保留在全部机会分母。

四开发用户前8会话已从各自空库形成，实际分母为32会话/73QA/72原生更新；
统一评分补充及来源提案对照、全部提案审查已闭合，不用于跨版本排名。
Root选择benchmark Editor thinking=True作为v3唯一模型配置变更：初始形成两次均覆盖五类原话，
金额冲突两次均使用用户e3的18000，False两次都把assistant e2的20000写成用户报告。
这项选择依据已曝光Source切片，不依据参考答案；True仍有空提案、非目标计划替换、
跨单元keep、模态增强、主体及时间问题，不能宣称全面改善或正式编译通过。
Host保持False，避免将32768输出对照直接套入8192入口；Reader、温度、预算和Source提示不变。
v3同时纳入已闭合工程检查的CURRENT提示与两处写入前拒绝回执修复。
新冻结源码已复用原Host20输入/control闭合并保留全部失败；同版五方法完整预测已启动，
待五方法预测全存后统一评分。旧v2完整主实验准备仍为0 HTTP，不复用其银行或结果。
固定Native32的原选择与Root来源审查已逐字节复制到`native32-5019968-v3-prepared`，
drift配置位于`drift277-5019968-v3-prepared`；两者仍0 HTTP、无BenchmarkRun/银行构造，
待全部同版预测和评分闭合再调度，不把准备文件当实际结果。
Native/drift入口静态核对已保存在`native-drift-runner-review-5019968-v3.json`：
9份相关代码与冻结源码逐字节一致，两配置的30项共同设置与本次主实验一致；
固定选择/来源审查再次对应32事项、12会话、4用户，未构造runner、未读取银行、0 HTTP。
Native使用各方法真实维护前后状态，Actual/NeverWrite/RetainAll为退化控制；
后续实际成本包含隔离状态Reader、embedding及Judge，不新增Editor形成调用。
隔离Reader复制原银行并还原实际保存版本，原主实验银行不写入；完整复制仍含原轨迹数据，
这次静态核对不能代替后续实际读取包/来源范围核验。漂移沿各方法自己的完整会话顺序读取维护结果。
全部五方法预测及统一评分闭合后才调度；该核对不是Native/drift结果或独立研究确认。
原固定LongMemEval28题及作者callback适配配置保存在`external28-5019968-v3-prepared`，
既有相关语言/措辞/独立顺序控制在`controlled-5019968-v3-prepared`；两者均0 HTTP，
待开发证据与最终候选冻结，若最终源码改变则另建配置，不能把当前准备当确认结果。
原16保留用户的UUID与配置已复制到`reserved16-5019968-v3-prepared`，仅准备，
未调用数据加载器或读取保留用户语义；原B1/B2/M范围暂存，最终方法和比较范围尚未选定。
固定紧预算协议位于`m-tight-context-5019968-v3-prepared`：M同四开发用户前8会话，
上下文65536降为49152，输出32768与余量512保持，完整输入上限32256降为15872。
该协议仍0 HTTP；基线仅取同版完整主实验M已运行的对应子集，不另跑基线或拼接银行。
两项均待完整主实验与统一评分、必要开发评价闭合；最终源码变化时保留准备身份并另建配置。
五组原Host公开输入与原评价control已逐字节复制到`host135-historical-inputs-prepared-v1`，
逐组核对合计135案例/192消息/145原文Source/1064有序候选；0 HTTP、未初始化银行。
该输入准备未选择最终Host方法，control仍仅用于评价，不提供给方法开发者；
冻结后新故事尚未生成，旧输入复制和离线兼容性检查不能当真实模型通过。
Root另将Host20两条遗忘请求的实际工具schema、参数、已交付读取凭据和无正文状态
交给恢复开发者隔离审查，目录为`host-forget-contract-5019968-source-only`，`review.json`已闭合。
逐条核对15次遗忘：更正链2次真实可见性撤销、3次写入前无效果拒绝；业务链10次全部拒绝，
零实际遗忘。没有一次read_handle参数等于已交付凭据；更正参数增加字面反斜杠，业务参数
使用record ID或自造组合等。业务唯一read_source是第4次共享读取，实际`read_limit_exhausted`、
limit=3。已确认模型选择器误用及预期额度耗尽，未证明正常合同接线缺陷，因此无源码补丁。
开发者11项JSON机械断言通过；0 HTTP、0运行时Store/backend写入、0输入重放，未跑pytest。
该Source-only审查不是模型重跑或独立研究确认，原失败及主实验冻结源码保持不变。
四开发用户的实际元数据已复核为每法277会话/705QA/595更新，均无generated-QA会话。
Root的一次元数据命令在uuid过滤前解码了所有JSONL行，只输出四开发用户计数；
未对未选用户语义审查/调参、未传入方法Worker。该程序解析事实和随后仅选中行加载的复核
保存在`development-metadata-validation.json`，不宣称保留用户从未被程序解析。
最终仍需同版五方法各277会话（合计1385）、
原 native32/12会话/4用户、drift/recovery、必要 M 消融与紧预算、最终冻结后的16保留用户、
LongMemEval、RawRAG/RollingSummary/A-MEM真实适配，以及 Host135case/192message 和新故事。
六项最终交付和方法选择均未完成，Product 仍为 NO_GO。工程可用、模型语义与科研优势分开判断。
