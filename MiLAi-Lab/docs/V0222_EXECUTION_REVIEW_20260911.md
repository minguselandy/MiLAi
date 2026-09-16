# V0222 执行范围与阶段审查

日期：2026-09-11。审查角色：独立 subagent。状态：`REQUIREMENTS_REVIEW / NOT_A_LIVE_ADMISSION_PASS`。

本审查完整阅读了仓库 `AGENTS.md`、[V0222 Goal](../studies/active/MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md)及[后续规划](V0222_后续执行与Memory再准入规划.md)，只读核查了旧 wire 编译和 HTTP 接线源码及部分冻结证据。尚未审查新批代码、manifest、全部历史账本或实际 HTTP 结果。本文不预填任何实验门 PASS，不修改旧批停止锁。

## 1. 新指令与授权的边界

本次用户指令为：详细阅读并执行 V0222 Goal，执行后进入后续执行与 Memory 再准入规划，遇到问题反思改进、保持探索性，并以 subagent 代替人工授权、标注和审查。主线程确认没有另外的阶段授权原文。

据此可执行文档已具体规定的有界工作及其条件分支；文档成文时的“只交文档／0 分配”应保留为历史状态，通过新增执行附录记录更新，而不是删除。授权来源是本次用户指令，subagent 是受委托的阶段准入审查者，不是新用户，不能把审查意见伪写成一条新用户授权。

| 范围 | 本次指令的执行解释 | 不能由审查代替的证据 |
| --- | --- | --- |
| P0、P2及实现回归 | 允许离线实施；P2实际修复仍依赖合格字符串信号 | 完整审计、代码、负控、原合同不变 |
| P1 | 新批最多24次，首遍12次，条件第二遍12次 | 请求封存、独立审查、身份容量、费用与安全门 |
| P3 | 最多16次，仅一个合格修复候选；首遍8次全过才第二遍 | P1选择证据、P2回归、逐实际请求容量 |
| P4 | 最多24条链／96次，仅P3全部通过后 | 新scope冷链、原执行器、独立实际效果 |
| E1 | 条件未来阶段，16条链／80次上界 | P3/P4真通过，具体故障时点、恢复政策和合同先冻结 |
| E2 | 条件未来阶段，16 episodes／256次上界 | E1真通过，自然动作合同及评分先重新准入 |
| M0/M1 | 条件未来阶段，首波14 episodes，满足预定有效性门才全部12B复验；全路径≤26 episodes／416次 | 合格root、自然A、双呈现、冻结事件与独立标注 |
| H-P | 无信号时必须交付提示分支计划；不自动获得P1剩余额度 | 在线策略原文未给具体次数，必须另立有界合同并明确阶段准入依据，独立审查不得默许无限调参 |
| 开放机制／独立确认 | 不是当前自动执行权限 | 跨root证据、简单对照、独立合同；不得打开受保护题池 |

每个新批必须绑定执行指令来源、阶段、绝对路径、唯一ID、代码与输入hash、模型参数、到期时间、次数及停止策略。未来阶段不能仅凭本审查表“预授权已通过”：须在上游实际结果出来后，对具体冻结实例重新审查。新修复候选、未列出的模型/服务/新题、扩次数或延长期限不能冒充同一合同内的继续。

HTTP-only、模型并发1、4096输出、65536上下文、raw cap=null、Judge=0、云端回退=0保持。禁止GPU/驱动/容器探测或操作、重启升级共享服务、读取HF凭据全集、Product/A0/State改动、开放 candidate 57／26 reserve／确认池。subagent委托不解除这些限制。

## 2. 发出P1前必须完成的检查

| 编号 | 要求 | 充分证据；当前审查状态 |
| --- | --- | --- |
| A1 | 实际链路排除可见H-I问题 | expected→canonical→wire→保存并真正发送的HTTP bytes→raw→字段diff；字符串出现位置/次数、Unicode与UTF-8长度、转义层和指令冲突；待新P0制品 |
| A2 | 全量字符串约束索引 | 四root、25对象、full/finish八合同的JSON pointer与组合上下文，关键字和同名业务属性分开；待审 |
| A3 | 合法/非法边界 | 完整校验器正负控、旧参考与失败原文；decoder membership无法观察则UNOBSERVED；待审 |
| A4 | P1单变量 | 三个唯一合法合成目标/hash；每个夹具四条件的实际messages、参数、权威Schema逐字相同，唯一差异是wire精确两个关键字；待审 |
| A5 | 全24位置与选择器先冻结 | 首遍T1→T2→T3、D00→D10→D01→D11；第二遍全部12位置反向条件；触发/选择规则的独立单测；待审 |
| A6 | 历史承接 | 所有旧账本路径/hash及最新V0221结算账绑定；旧已知30,085 raw、旧未知预约28,284原样保留，总实际未知；待逐账本复算 |
| A7 | 新批安全 | 不借旧停止批；跨进程单写者、一次性launch、不可重启/复制目录恢复额度、阶段/期限/身份漂移、新未知全批停止负控；待审 |
| A8 | 诊断隔离 | transport→原始证据/usage→离线验收；无Session、World、dispatcher、Note连接；检查可达调用链，不只搜类名；待审 |
| A9 | 错误分流 | HTTP200且用量可信的预定内容失败记结果继续；传输/用量/证据/权限/身份漂移停全批；每失败占位置，不重发；待审 |
| A10 | 实际容量和身份 | 最终wire/messages各条件在线tokenize，参考完整输出也计数；模型、context、HTTP版本记录；不声称镜像/后端完整鉴证；待实际预检 |
| A11 | 封存与评审闭环 | 新入口/所有依赖、夹具、规则、授权来源、准确scope和hash封存；独立review发现项真实解决后才能准入；待审 |

P0可以继续做零生成分析和实现，不必等上述所有运行证据；但A1—A9、A11必须在任何P1生成前满足，A10须在发送前实际验证。发现实际载荷损坏先修接线并冻结修订，不能边用损坏请求生成边研究。准备修订能否另建目录须遵守原文“没有生成/tokenize/launch”的限制；有真实HTTP活动的失败不能伪装成零运行修订。

## 3. P1四条件的可识别性审查

四条件构成精确 `pattern="\\S"` 与 `minLength=1` 的2×2 wire移出对照；只要A4满足，可以隔离这两个wire因子及其交互对应的当前HTTP行为差异。完整校验语义中，存在非空白字符已蕴含长度至少1，因此D01主要检验解码器实现/规则交互，不是一个新的业务语言。这不削弱其诊断价值，但不得误称两个业务约束彼此独立。

必须避免以下混杂：

- 条件名、不同兼容说明、不同权威Schema或不同提示位置进入messages；应在序列化后的实际发送对象核对，不能只比较准备函数参数。
- T2比较JSON转义拼写而不是解码字符串；T3调用strip/trim、Unicode归一化或空白修补。
- 将三种夹具拆成事后挑选的多个目标；每类一个事前唯一字符串。T1可以在同一字符串内同时含合成地址和普通多词文本。
- 冷客户端误称冷后端：新进程不清空共享服务缓存，也不证明统计独立。固定seed/温度与两遍反序只降低部分次序疑虑，不能产生无偏效应估计。
- schema通过与精确复制通过合并；短字符串可能完全合法但不保真，非法JSON也仍需保留原始成本和预定诊断标签。

固定选择器必须机械且可反例测试：首遍至少一个同夹具D00不保真而移出条件保真才进入第二遍；候选须三夹具两遍6/6，并有至少一个夹具两遍都相对D00改善；优先最少关键字，平局D10先于D01，D11最后；D00同样6/6不选更复杂策略。第二遍只复测有利位置、只要求一遍改善、按平均分择优均不合格。首遍全失败、全成功、无配对改善，均不消耗第二遍。

这个设计可选出一个兼容候选，不能证明整个JSON字符串语言等价、具体内部后端故障、长业务请求已修复或Memory因果。原完整来源与请求长度可能仍影响P3结果，应保留分层结论。

## 4. 先前pattern源码线索的审查

已直接读本地 `tools/v0220_wire_contract.py`：`pattern`、`minLength`、`maxLength`在LITERALS中被原样深拷贝；唯一被延后的业务关键字是uniqueItems。`prepare`额外附加完整权威Schema与统一兼容说明；输出以原完整Schema验收。故“旧wire没有改变字符串规则”有本地可复核依据。

旧HTTP Provider确实保存将传给HTTP客户端的raw bytes，并通过`content=raw`发送；P0仍需核对具体失败请求的文件hash与实际解析值，不能凭这一代码结构直接宣布没有双重转义或提示冲突。

本地历史服务源码快照显示vLLM XgrammarBackend会调用`compile_json_schema`，但此快照只证明历史源文件内容，不证明当前请求路由到该后端。Goal记录的XGrammar v0.2.3 `GenerateString`提前返回正则生成结果的上游线索，在本次无网络审查中未重新取得该C++文件，因此保留为“此前静态查阅的来源线索”，不能称本次独立复核或线上根因确认。P1行为证据即使符合假设，也不填补当前后端内部可观测性的缺口。

P2只能按事前选择器作用于已审阅正向string节点中精确值规则，列出所有命中pointer；不能按recipient/summary/root或答案路由，不能顺便删除任意regex、format、其他长度规则。保留uniqueItems完整后验，原canonical业务接受集合不变；新wire允许集合变宽而非解码等价。未审阅组合或引用应拒绝而不是递归删键。

## 5. P2—P4阶段review要求

P2先复核P1全部位置/原始响应/usage/选择器复算，再审变换白名单与反例：同名属性、enum/default/examples不误改；负向/引用/未审阅运算符拒绝；全部完整对象及required、enum/const、数值、身份、scope、CAS、数组唯一性保持。完整值比较需类型敏感，不能让Python的`True == 1`替代JSON类型核查；对象键序与合法转义差异可接受，值归一化不可接受。

P3必须重新冻结八合同的全部合法对象/完整来源与旧固定目标，逐最终请求容量预检，独立确认唯一修复版本。所有输出先保留raw/usage，再严格JSON、原完整Schema和意图，绝不接业务dispatcher。首个非预期失败停止候选；16位置中未运行项明确列出，不挑短值/finish填补分母。

P4仅P3 full 8/8、finish 8/8真通过后准入。独立审查24条链规格、冷scope/空World、原Session/ActionAdapter、完整授权动作和读回计划；mock验证输出在意图验收之前不能写入。实际审核必须从独立SQLite/operation账、公开receipt和回读复算目标、值、顺序、版本，不仅相信worker PASS。首错停发，不自动改expected_version、不新建operation重试，不用finish/Note代替业务效果。

## 6. 后续路线的独立阶段门

E1发送前冻结两类故障各自正确恢复/停止标准、故障实际触发证据、拒绝零副作用、最多3次后续模型修正机会和全链≤5次；先做零模型的响应丢失/未知提交故障注入。`NOT_EXERCISED`不算PASS，盲目CAS加一与提交率不能替代适用条件核验。

E2发送前重审自然动作合同，尤其save_note不继承enable_note=false的八Schema成绩；无Oracle/答案注入，N0-exec与R0-exec完整资料和起点相同，九项争议和多解/UNKNOWN规则必须在模型输出前冻结。逐root四个完整episode全过才合格；至少2root/2family且每个Memory用root合格。仅前两根的先行配对不自动代表全部16episode完成。

M0/M1须先冻结A任务、外生事件、完整公共输入、truth/争议规则与三臂政策；自然A的NO_WRITE、错误/未决Note保留，不重试直到好Note。标注subagent应收到事前冻结rubric与公开来源，尽量屏蔽arm/后续结果，保留来源定位与争议，不生成可供actor复制的gold。必须证明committed→cold public read→bytes presented及新观察呈现；缺机会记NA。复验触发只依赖预定执行/冷链有效性门，不依赖N1是否更差；重复全部12B且不重写A。

机制探索只在规定跨root/family现象、有效旧新双呈现和普通复核不能解释/解决后开放；普通方案获胜可关闭当前机制动机。不得用探索性要求合理化新题曝光、反复挑样本或免除独立确认合同。

## 7. 审计交付原则

各阶段分别交付manifest、分层结果、三账、未运行位置与下一步决定。旧历史实际合计仍未知；不能把预约28284当实际成本，也不能只记V0221的27864漏掉旧2221。tokenize、模型生成、Agent工作用量分开；HTTP成功、Schema成功、意图成功、业务效果成功分开。

每次实现交付运行边界检查、完整pytest、Ruff、Mypy、构建；Product-backed另需公开版本pin，但当前不得凭此扩展到Product。工程测试绿灯不代替实际模型与业务门。报告交付可成立而能力门未满足；目标覆盖后续路线时应明确哪些条件已触发、已执行、未触发或仍待具体合同，不能把P1局部完成称作全路线完成。

## 8. 首轮诊断与transport代码审查

本轮审查对象：`tools/v0222_diagnostic.py`、`tools/v0222_transport.py`及两个对应单测文件。未审查尚在实现的prepare/preflight/worker/runner和批协调器；代码正在开发，以下是审查时快照的发现，后续修复应追加复核结果而非把发现改成从未存在。

执行 `uv run pytest -q tests/unit/test_v0222_diagnostic.py tests/unit/test_v0222_transport.py`，结果 **22 passed / 1 failed（1.29秒）**。另运行两个只用内存MockTransport／临时测试目录的反例脚本，无实际网络。

| 编号 | 发现与复现 | 发送前要求 |
| --- | --- | --- |
| R1 | `Transport.verify()`不在generate的fatal捕获范围。先正常verify，再让models返回503，异常后batch未停止且context仍65536；随后generate确实可继续发送 | 身份HTTP失败/漂移须中央永久stop并使旧context失效，增加后续verify/generate均不能发出的负控 |
| R2 | HTTP envelope用`response.json()`解析；Mock响应包含两份冲突usage（477与82），静默选择最后一份并结算82 | envelope至少拒绝重复键／非有限或畸形JSON，冲突用量不得记可信已结算，保留原始响应并UNKNOWN停发 |
| R3 | `observe('{"text":"\\ud800"}', 'T1')`和`\\udfff`均在差异hash时抛UnicodeEncodeError | 明确未配对surrogate的诊断分类并保留原输出；不得让可信usage的纯内容失败意外成为全批fatal；增加合法surrogate pair正控与非法单元负控 |
| R4 | 单测`test_wire_drift_stops_before_tokenize_or_generation`失败：exact_wire闭包引用的body与测试修改对象是同一个可变对象 | 测试/实际worker的expected请求必须独立深拷贝或冻结hash；漂移拒绝测试重新通过后才可作为封存证明 |

已有可接受的局部证据：三个目标在完整权威Schema中合法；四条件恢复两个被删关键字后与canonical对象完全相同，消息与其他参数未改变。T2包含真实换行/制表符和反斜线，T3保留边界空白；比较器区分bool和数值、保留数组顺序，接受对象键序及JSON数值的数学等值，不做字符串归一化。23项测试未覆盖完整选择器或全批继续语义，这些仍待协调器和runner审查。

transport先保存原始HTTP响应，再记录可信usage，之后读取可见文本；普通内容`not json`与合法但错误短字符串均已结算且未触发停发。500、timeout、缺失usage、bound mismatch、缺失id现有负控通过且generate无自动重试。但R1/R2说明现有局部负控不足以支持“全部身份与可信用量失败均安全停止”。

可达新路径未见直接设备/容器调用。继承Provider只初始化HTTP客户端；导入的旧`backend_identity`包含容器操作函数但新路径未调用。另有`v0213_provider→replay_v0213_cost`的历史间接导入，会加载transformers/tokenizers（本地打印无模型框架提示）；当前测试没有模型加载/设备探测调用，不应将提示误报为GPU调用。P1实际worker仍应审查完整调用链，避免误调用旧backend入口或Tokenizer模型加载方法。

## 9. 第二轮P1调用链审查

本轮新增阅读prepare/preflight/worker/runner、批协调器及用户执行补充。R1—R4均已有针对性修订，运行诊断、transport、batch三组单测 **60 passed（20.32秒）**。verify清空context并在异常中央stop；envelope拒绝重复键／非有限值后才结算；孤立surrogate分类且可见文本用ASCII JSON转义无损存储；漂移测试expected独立深拷贝。这些修订解决首轮已复现问题，不代表整批准入完成。

36小时只作为一次性授权容器时间窗，给离线分析及条件阶段准备留空间；实际P1/P3阶段1800秒、P4阶段7200秒、链300秒、单次请求60秒不变。这样的事前具体化没有扩大阶段请求上界，且不得在到期后续期重启同批。

发送前仍需处理或提供充分证明：

| 编号 | 二审发现 | 要求 |
| --- | --- | --- |
| R5 | 独立`Batch._observation`只比实际request与自己的RESERVED hash，未与冻结P1-reference wire及条件对照；现有测试`mock_only`请求也可验收OBSERVED | 独立核对实际发送对象与冻结wire、fixture/condition/参数；绑定tokenize证据；错请求/错条件即使复制正确也不能作为有效单元 |
| R6 | 三模块测试分别用FakeBatch transport及人工构造回执，未覆盖真实接线全链 | 增加真Batch＋Transport＋worker／parent的零网络MockHTTP端到端测试，覆盖原始账镜像、内容失败继续、首遍/第二遍选择与fatal停止 |
| R7 | `httpx timeout=60`是网络操作超时配置，不能单独证明生成请求总墙钟≤60秒；子进程310秒也不是该限制 | 以实际总deadline约束生成HTTP，并测试慢响应／间隔数据不绕过上限，不仅记录事后超时 |
| R8 | preflight只冻结result，未绑定tokenize和identity全部原始制品；调用列表在response返回后才append | gate依赖原始request/http/identity hash，篡改或缺失使后续停发；超时在线尝试也应列入计数与异常证据 |
| R9 | runner首遍和最终decision/save/freeze在episode try之外 | 决策/封存异常统一stop并尽可能交付失败结果、费用和未运行矩阵；不得因意外栈退出丢失阶段收口 |

当前worker只接Transport与observe，没有实例化Session、World或dispatcher。后续P3/P4尚未实现的准入不能从P1代码或本审查取得；root建立后还需对实际binding、P0审计、各冻结请求、授权来源与账本做只读最终scope review。本轮依旧未发送任何真实HTTP。

## 10. 第三轮修订与P0独立复算

新`v0222_http.py`使用主线程POSIX ITIMER_REAL约束HTTP总墙钟；拒绝覆盖已有timer，退出恢复handler和清理本次timer。身份、tokenize、envelope统一严格JSON解析。相关Mock慢响应测试验证实际中断，不只检查传入timeout数值。preflight在发出前记录attempt，异常保存error，result.files列出全部请求/HTTP/identity制品；runner外围统一捕获决策和封存异常并stop、交付尽可能完整的失败快照。R7/R8/R9代码修订与相关局部测试成立。

运行HTTP、diagnostic、transport、integration四组单测 **39 passed（4.52秒）**。真Batch＋worker＋Transport测试覆盖单位置exact/短值/非法JSON与冻结前后raw/usage篡改，确实完成中央账镜像、独立finish和未实例化World/Session/ActionAdapter的检查。它不是实际冷进程完整矩阵成绩；完整次序/选择器另由batch测试，冷进程和真实服务由随后阶段证据承担。R5正在另行修订，仍待最后复核。

P0独立调用`build_audit()`重新读取全部305个输入并重建完整审计，结果与落盘audit逐对象完全相同；305个源hash全部匹配，compact.audit_sha256匹配audit。确认8合同、25对象、96参考请求、22校验边界例，差异仅recipient及summary；decoder membership仍UNOBSERVED。该复算没有网络或模型实例。

准备器尚需把这个事实变成发送前防漂移规则：不能仅检查P0 result.status；应核对audit_sha256、audit.inputs每个当前hash，并把这些依赖纳入新批冻结inputs或等价artifact.files。当前P0内容没有发现错误，但仅冻结两份总结文件不能阻止其源证据事后漂移。无需修改旧P0制品。完成此项及R5后，最终准入仍需核查实际新根binding与scope_review，不提前预填PASS。

## 11. 封存前复核

准备器已检查P0 audit_sha256、全部305源hash，并去重纳入新manifest.inputs，P0依赖防漂移项关闭。批协调器已对全24参考位置和元数据、权威Schema、目标、唯一允许的wire变换、同夹具canonical一致性做独立校验，并把所有参考文件及每次tokenize三件原始制品绑定；实际请求必须匹配对应冻结wire。worker的expected是独立hash字符串，前置比较和独立审计以fingerprint区分bool/int/float，R5关闭。

在各实现者确认文件稳定后，独立重跑batch、integration、HTTP、transport、diagnostic五组 **87 passed（33.39秒）**，选定全部新模块及测试Ruff通过。此前一次测试执行中并行源码修改曾按设计触发IMPLEMENTATION_DRIFT（50 passed / 1 failed）；没有绕过校验，稳定后重新验证。

随后仅补齐已知内容失败分流一致性：父级独立JSON解析同样捕获RecursionError，避免2201字符深嵌套内容在诊断层False而父级误记fatal。该修订不放宽HTTP、费用或业务验收。封存前没有发现其他未决代码阻断；实际root的最终hash／scope审查以及HTTP容量门仍是发送前必需项，本文不替代它们。

## 12. 实际冻结实例的范围审查

已对 `/cra/memory/mx_memory/evidence/v0222/20260911-http-r1` 完成最终只读核验，binding SHA256为 `f6abde2c7258eba7288aa0cb7c74e03aafb97a486127f9b7a5827525c30c70d9`。39代码依赖（含封存副本）、312输入hash全部匹配；24实际canonical/wire/output及目标、顺序、消息一致性独立复算通过。用户原文及36小时总窗／各阶段原限额映射一致，三历史账为已知30085 raw、唯一旧未知预约28284、总实际未知。审查时launch和events均0，64个阶段位置全部PENDING。

已新建 `scope-review.json`，状态 `G_AUTH_SCOPE_REVIEW_PASS`，明确review不是用户同意来源；86份直接证据hash绑定manifest、授权、P0报告、参考索引及全部72个P1请求/参考文件，并通过manifest传递绑定全部依赖和输入。检查了主线程提供的工程检查制品（1720 passed／1 optional skip及五项检查），不伪称该全仓测试由本审查者独立重跑。

本次scope通过只允许P1继续进入HTTP身份/容量预检，尚未证明运行容量、字符串信号或意图保真。P3/P4仍为条件范围、NOT_ADMITTED。P4旧计划继承的initial_state_sha256未随新scope重算，不能作为新World准备证明；主线程已确认在P4阶段单独封存resolved-spec/reference，显式保留原字段来源并按同一公共起点、新scope重算后独立审查，不修改原manifest。本项不影响无World的P1。

审查者未注册artifact、未launch、未发送HTTP、未操作设备／容器／服务；可变batch.sqlite未纳入文件冻结。
