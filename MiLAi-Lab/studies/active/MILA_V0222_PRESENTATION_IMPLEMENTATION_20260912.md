# V0222 独立意图呈现完整门：离线实施进展

日期：2026-09-12。状态：`P3_STOPPED_EPISODE_DEADLINE / TERMINAL_REVIEW_PASS / OFFLINE_ENGINEERING_FOLLOWUP`。
最新[完整门终态](MILA_V0222_PRESENTATION_FULL_GATE_20260912.md)及[结果JSON](MILA_V0222_PRESENTATION_RESULTS_20260912.json)：
12正式PASS，第13因阶段期限失败，13生成449759raw全部结算；余3P3／24P4未运行。
下文运行中检查点均为历史观察，不能覆盖已停终态；独立终审通过，新离线组件46项测试与独审通过，
组件基线全仓session6214已2434 passed／1 optional skip（1210.20秒），[组件边界与后续证明](../../docs/V0222_ADMISSION_READ_SCOPE_OFFLINE_20260912.md)另列，无新批发送。
实际文件规模/JSON和显式V2设计已独审；后续[证据适配层R2](../../docs/V0222_SCOPED_EVIDENCE_IMPLEMENTATION_20260912.md)
64项局部测试及独审、5865路径/hash新旧完整覆盖对照通过，全仓pytest89818已2498PASS/1skip；
随后新增[历史账适配器](../../docs/V0222_SCOPED_HISTORY_IMPLEMENTATION_20260912.md)，不在上述已收集基线内；
尚未接入Batch，也不在上述已完成基线覆盖内，更未证明阶段加速或准入。
这是[唯一候选设计](../../docs/V0222_PRESENTATION_FULL_GATE_DESIGN_NOT_ADMITTED.md)的实施记录，
不是新的模型成绩，也不是整体 Goal 结项。
可机读进度及三账见[紧凑结果](MILA_V0222_PRESENTATION_OFFLINE_RESULTS_20260912.json)。

## 完整离线参考已实际验证

证明根：`/cra/memory/mx_memory/evidence/v0222-presentation-offline/20260912-full-matrix-r1`。

| 证据 | 实际覆盖 | SHA256 |
| --- | --- | --- |
| `summary.json` | 原四根16个full/finish、80份P4参考、24条完整链、40个独立离线World；904文件 | `bbbf0d353038512fe98f749a2abc0c51283852b70e28e307a346e9257ec14e2c` |
| `current-auditor-revalidation.json` | 严格轮次类型修订后，对原全部96参考/24链追加只读重验；905文件、当前源码闭包 | `bbf778e7f440436eac5cd1b87967cac81bdad63f79fd2d8850c4afba313127b2` |

参考由原 Session／ActionAdapter 在全新 scope 下执行，不是只转写旧参考。
原四根、完整资料、动作值、顺序和完整链意图保持；仅派生新ID、scope及初始状态hash。
独立审计从原公共资料重建请求，复算 B1→D11、完整Schema、真实SQLite操作账与效果、公开回读及finish。
追加重验没有重建World、重发模型或覆盖原证明。
`p0_audit`已独立复核上述文件、完整依赖hash及当前审计实现；不将离线PASS解释为decoder membership。

## 已发现并修复的反例

- 首次实际回执只校验Schema和缓存hash不足：同步篡改turn与待发历史会把伪回执送进下一轮。
  Provider现先对照实际World操作/公开读取核验，再采信回执；不从参考答案生成下一轮输入。
- 意图失败必须先永久停批，再保存diff；保存诊断再失败也保留原始停因。
- 审计不能只收集全部文件hash：额外未记账HTTP文件必须拒绝。
  已要求Provider完整文件集合与真实预约一一对应，独立核验4096预约、累计cap=null、lineage与release证明。
- `100.0`不能冒充整数tokenize回执，`True/1.0`不能冒充第一轮编号；新增严格类型负控。
- 每轮公开read、operation_status和finish回执从实际提交前缀独立重建，不能只验证最终records。

Provider修订版38项测试通过，独立复核其中新增针对性9项通过。
审计33项测试通过；独立复核分别覆盖25项与新增8项。
准备入口4项、封存证据门10项测试通过。这些均为离线工程测试，不计入模型保真分母。

## 正在收口的接线

- 完整新Batch＋Mock HTTP＋原Session＋真实独立审计的16→24集成及4项失败负控已通过，
  并已独立重算40个episode；不能将其与真实模型成绩混为一谈。
- worker/runner32项测试通过并经独立复核；单次冷进程、父子PID、实际阶段deadline、超时停批后回收保留。
- 预检主体已覆盖104/488份回执、实际完整输入/输出容量及失败停批；独审发现构造失败停锁与
  身份GET的attempt保存后再次准入两个缺口，现已用新入口修复并独立复核，旧冻结helper未改。
- 单独预检有限窗为P3 1200秒、P4 2400秒，包含本地依赖复核；模型阶段仍为1800/7200秒，
  每链300秒、每模型HTTP最多60秒，不借预检窗延长模型阶段。
- 新封存入口要求当前完整源码/测试依赖被六项工程检查证据覆盖、当前审计器完整96/24证明；
  准备成功仍需具体实例独立范围审查，不能凭状态标签直接发送。

独立审查制品均在上述证明根新增，不覆盖早期记录：

| 文件 | 有限结论 | SHA256 |
| --- | --- | --- |
| `independent-implementation-review.json` | Provider／审计／worker／runner／identity／预检／Transport的指定离线审查PASS，不自签pure或完整Batch集成 | `60b0f50e29c9dfc9cadd202faacf338c07255bfa5ed709dbe007420db4ba8c91` |
| `independent-preparation-review.json` | 准备／封存门与40行旧→新ID、scope、初始hash派生审查PASS | `354f72a97e81f23e2d5759a4d179e8f18cc3d03d2bf45e3bebacd35571fad25d` |

主代理再次核对前者16源码/测试＋2证明hash及后者12直接绑定文件，均一致。
预检/identity新增独立57项、Transport35项测试通过；全仓回归终态为2388 passed／1 optional Host SDK skip，
1203.68秒，session18638、terminal chunk8df8dc。Ruff、边界、Mypy（39源文件）、构建及diff均通过。
检查前后60项执行源／测试传递依赖hash一致。
首轮集成曾通过16 P3和4 P4，随后因并行开发改变封存源而以IMPLEMENTATION_DRIFT停止；
该失败保留，不弱化漂移门；后续统一同版全仓回归已包含完整集成复验。

新增制品：

- `engineering-checks.json`：`85cd122a5b804128b33e1cb1e2e76845699e0b3cfe6fbee475eaa8e593346378`，六项工程检查及60依赖。
- `independent-pure-integration-review.json`：`02dae3a7ed50db7a2bf9ede1eade521a243cc45f2d52c828f99dcd30fb15cc28`，纯合同非作者59项测试与集成静态边界。
- `integration-observation.json`：`f430192d7e813bec8d27ae5eca6b32b4d4c136f8705207d570dcfd18599012b3`，作者观察，非独立审查。
- `independent-integration-review.json`：`3396538016b35e1c4edd817d93935194e4eacf3179f158fb7eba48c54b3b6f04`，
  40实际模拟审核／中央地方384事件／P3gate独立复算；63长期依赖，不把临时测试树作为正式依赖。

完整模拟批为96次Mock生成（16 P3＋80 P4）、11520模拟raw，24World、32提交、24回读、24finish，
40 PID为模拟值；472份Mock HTTP收据。模拟历史526已知raw与真实历史631670严格分开。

## 唯一正式实例零HTTP准备完成

根：`/cra/memory/mx_memory/evidence/v0222-presentation/20260912-http-r1`。
binding：`bcc255fcbf4ab390f295b601cc353f98c23fb6800d8bfe54349bdb2325b197e1`；
manifest：`1a50343391ff5342b9b80f69801de2659019b5470c4f1fe606d97ce48440c464`。
60执行依赖、4486输入已封存；源码／测试及原设计文档不得继续改写。
本地完整参考准备已成功结束（session63661，terminal chunk0f15e2，exit 0），
状态为`OFFLINE_INSTANCE_PREPARED_SCOPE_REVIEW_REQUIRED`；正式16＋80参考、24链与40World通过，
`full-reference/prepared.json`绑定903项文件。具体binding的完整独立范围审查已通过：
`scope-review.json` SHA256 `4813e370efb2618094d50abb93c99e106006ab12018b06181b8c069e0e23c33b`，
覆盖全部96参考、40World及5457项稳定依赖；主代理再次hash复核并用原Batch入口登记成功
（session83193，terminal chunke0f251，exit0）。范围审查不构成新的用户同意。
随后唯一P3 HTTP身份／完整容量预检通过（session77952，terminal chunk7e8dc3，exit0）：
16参考、32tokenize、前后4身份GET，104证据文件。结果SHA256
`dd13e634b465e204d7dd34fa707471f2f326c7b864308ebbd5b26569e3c42660`，主代理复核全部hash一致。
已启动唯一P3真实生成阶段（session35358，launcher PID1865200），首个新冷worker PID1866342。
P3运行中，尚无完整门PASS；P4未触发。
后续只读检查点：P3-01实际PASS，原完整意图保真，1次生成28170raw全部结算、无未知／违规／业务派发；
冷worker耗时119.33秒。P3-02正在运行，剩余14个P3与全部24条P4仍待定，整批stop=null。
此为运行中检查点，不是完整阶段成绩；必须继续等待同一session35358，不能重启。
P3预检另经subagent独立只读重建16参考及全部104文件通过（session13563、terminal chunkf26942）；
36份实际HTTP回执最长0.212秒，未触发5秒界限。

最新检查点（tool chunk2a52e8）：第一遍8/8 PASS，full4/4、finish4/4，265607raw全部结算，
这8个完成位置无未知／违规；主代理复核8份已保存审计的检查项、费用与hash（chunk54250a）。
第9个位置已由新冷进程进入第二遍，余7位置待定；阶段剩余约625.5秒，stop=null。
同一session35358仍存活（poll chunk07574f），完整16门及P4前置条件尚未满足。
其后只读检查点chunkcef58f：9 PASS，第10位置运行中、余6待定，293777raw已结算、stop=null；
剩余约506.7秒，session35358存活（poll chunk6c547c）。不把运行中快照当完整终态。

### 运行中时间窗风险（不是终态失败）

后续检查已完成P3-02 PASS，23640raw；前三个位置PASS时累计106248raw。
独立subagent `/root/batch_guard`只读复核已完成01/02的exit与HTTP回执：冷worker分别119.328／116.010秒，
计时HTTP合计6.327／3.424秒，非HTTP余量113.001／112.586秒（包含校验、启动、调度及IO，不能全称CPU）。
成功路径静态约15次authorize、14次check_journal，包含44历史账、冻结输入与历史闭包、全部artifact重复核验；
父finish及最终16项gate复算另计。仅按这两个worker均值外推16次约1882.7秒，已高于冻结1800秒，
因此记录时间窗风险，但不预填失败、不中断当前批、不延长时限或减少验收。
未来可补分段计时、在冻结前覆盖完整真实校验开销，并研究单次准入内去重；每次HTTP新鲜状态与完整
文件覆盖必须保留，不能跨准入缓存PASS。当前没有改实现、运行性能压测、操作GPU或服务。
准备进程没有重启，源码、测试及设计的冻结保持；主代理再次复核60项工程依赖和8项长期证明hash一致。

## 后续恢复阶段的只读缺口审查

独立subagent `/root/v222_review`复核路线与原公共接口，E1仍为`NOT_TRIGGERED`。
前置真实门通过后，仍须冻结16条五轮链、每根公开适用条件及变更事件、完整新历史账，
另建精确一次版本拒绝豁免、五轮原始历史呈现和事件感知审计，不能放宽当前P4停止规则。
首次拒绝无副作用应比较外生事件发布后、动作派发前后；澄清会真实修改pending，不能要求整链零写入。
旧operation重放返回原拒绝，未知提交不可按head猜测；须先完成响应丢失等零模型负控。
这些是后续实施缺口，不是新授权、模型成绩或E1准入。

新增subagent[四根公开事件标注草案](../../docs/V0222_E1_PUBLIC_EVENT_ANNOTATION_DRAFT_20260912.md)，
SHA256 `83a3110dd3057eb9050a0b67e2656a4e8b6c3c2c6dcf19ce314e64b5d13e5b82`。
主代理核验4个已暴露公开源文件hash及11个JSON Pointer片段指纹一致；没有发布事件或修改World。
租赁／Netflix仍可能允许合法更新报告，人员安置需核实发布权限与旧动作的事实依赖，
面试同意争议明确UNKNOWN、一次回读不足以证明旧结论失效。草案不是四根已合格的changed场景，
已交独立subagent复核，不能用它预填16链恢复门或为凑矩阵开放保护题池。

独立subagent `/root/p0_audit`随后核对公开材料及既有完整动作：草案的UNKNOWN边界合理，
但**不足以成立原16链E1合同**。租赁旧预算、Netflix共识、安置单席确有字段依赖，
不代表整个条件性报告必错或唯一合法行为是澄清；Netflix的watchlist链也不依赖该共识。
面试未核验新声明不能推翻原两份依据，保持UNKNOWN。下一步须逐根冻结具体初始完整动作，
建立字段—公开前提对应表、可信覆盖关系、事件前后完整current及多解／UNKNOWN判据，
再检验一次回读充分性和五轮路径；不能缩成有利root后仍称原16链。E1继续NOT_TRIGGERED。

## 费用、边界与下一步

正式准备和范围审查期间新增HTTP为0；P3预检已完成32tokenize／4身份GET。
P3真实阶段正在运行，动态HTTP／生成／raw账尚待终态汇总；不得继续将本批描述为零请求。
历史仍为45请求、631670已知raw，唯一旧未知预约28284；总实际仍未知，不把预约作为成本相加。
Agent工作量另列平台累计快照4902740 tokens（Goal updated_unix=1789154698，无token预算），
不是本批模型账单，不与Mock模拟费用或vLLM raw相加。
仅现有vLLM HTTP可用于后续模型交互；无GPU、驱动、容器或服务操作，无凭据读取。
旧P3永久停止和boundary终态保持；保护题池、Product/A0及Memory机制未开放。

后续顺序：完成独立终态审计 → 离线校验开销修订与完整证明 → 另行核对任何未来真实执行的范围与授权。
当前P3完整门未满足，P4/E1/E2/M0/M1均未触发；不得重启或改写冻结版本，整体Goal继续执行。
