---
status: ACTIVE
scope: RESEARCH_PROTOTYPE
parent: MILAI_LONG_HORIZON_EXECUTION_GOAL.md
reference_commit: 5e49cf9a7a2cc6eef78f0b76c089c2f1c95e70a8
---

# P10：原生外部记忆形成的小规模系统对照

v25已完成持久应用和三档历史边界，v24的F/R提示家族负结果保持关闭。总计划仍要求external baseline。下一步只比较一个有针对性的外部系统，检验原生自动摄取能否覆盖此前的记忆形成缺口；不重跑v25、不扩大benchmark、不改vLLM设置。

选择已下载的Mem0 OSS commit `f8082a7345dadd9e042ebbc40b57b1498c8f6d63`，版本2.1.0。来源、许可证见[既有来源清单](../data/manifests/contextual-memory-v3-sources.json)。这一固定版本的`Memory.add(infer=True)`采用原生ADD-only抽取/批量embedding/实体关联，原生search融合多个信号；不是托管平台的公开分数复现。Memobase/Graphiti要求额外服务，不同时扩展。

不能把Mem0当作v25同ID修订的严格替身：原生抽取会新增多个条目，不保证整条计划保持同ID；纯`infer=False`加显式update虽可匹配CRUD，却绕过自动摄取。因此本阶段转向已有自然形成输入，明确是系统级比较，包含自动摄取时机、检索合同和额外模型调用差异，不归因为SER机制或单一算法变量。

## 固定最小范围

原样复用[v24四例输入](../data/diagnostics/milai-lifecycle-v24-formation-inputs.json)及[原rubric](../data/diagnostics/milai-lifecycle-v24-formation-rubric.json)：两个未来需要的事实/业务回执，两例临时计算/一次性格式反例；每臂四例、六session、六公开消息。均已暴露，不能称为unseen。business fixture仍是原静态工具回执，不冒称v25的持久世界。

两臂依次运行，各用新namespace/存储/线程：

1. 公开LangMem B1：普通Host自主manage/search，不加SER、F/R或自动摄取。
2. Mem0 OSS原生自动摄取：相同Host和业务输入；每条公开消息成功完成后，将真实user文本和最终assistant文本交给官方`Memory.add(infer=True)`。Host只暴露绑定用户scope的原生search工具，记忆管理由后台原生自动摄取完成；公开前固定对应system/schema和返回格式。这些与B1手动CRUD工具合同的差异属于所比较的系统策略，不声称首请求相同。

Mem0的`parse_messages`仅序列化system/user/assistant，抽取prompt也只收到该字符串。按标准聊天整轮摄取，不自行把tool消息伪装成assistant、不补充gold或未复述的回执。原始business回执仍保留在Host上下文和研究trace；若最终assistant漏述必要字段，记录为该系统的输入边界。摄取每个成功完成的公开轮次，包括临时控制与后来查询，不能按case ID、rubric或是否有未来用途路由。

保留Mem0原生search默认top_k20、threshold0.1及默认OSS特性；LangMem保持原合同。差异明示，不强行改成相同ranking或套用相同raw score意义。统计初次session结束的实际持久记忆、后来真实search送达、准确业务参数/回答、临时信息不必要持久化。所有失败计入分母。

## 适配与实施边界

Sol负责最小源码/config/依赖声明和必要窄检查；Root负责输入/rubric引用、协议/源锁、全部真实Host和embedding调用及结果；Luna high负责依赖下载和已授权Git提交。依赖安装使用独立环境或受锁定的可选组，不为新系统重写旧运行的环境回执。

使用官方`Memory.from_config/add/search/get_all`和本地持久Qdrant、SQLite history。只桥接现有VLLM客户端的模型/embedding传输、费用及并发1；保持官方抽取、去重、关联、排名和空结果/错误语义。若内部组件并发，实际HTTP经共享适配器串行化并记录该部署差异。不能改vLLM parser、thinking、容量、模型、embedding维度，不能通过stub或复制算法冒充Mem0。依赖只安装核心SDK与必要spaCy/fastembed；小型NLP/sparse资产由Luna提前固定并下载，不在真实调用期间隐式下载，不安装无关的整组extras。

自动摄取与Host请求费用分开，所有内生LLM、embedding、原生重试/回退及失败均进入连续账本。官方telemetry关闭，不发送运行正文至第三方服务。scope由适配器绑定运行/用户，不能由模型填写另一个用户；不把Mem0随机ID改成LangMem生成ID。已完成摄取与pending结果须区分，未知副作用不自动重试。同步原生search中的本地Qdrant实体并行无需禁止；模型与embedding HTTP仍串行。

只验证实际新增边界：原生SDK经过假provider的摄取/持久化/搜索与scope、整轮序列化和成本串行接线、已完成/未知摄取恢复、默认B1行为保持。不跑全套、不新增与实现镜像的测试。依赖/新入口有必要时构建一次；源码和适配合同冻结后才有真实调用。

## 判定与交付

先完成适配并记录实际官方API、依赖与model-visible合同，再冻结两臂全部运行。只跑这一对四例对照，除确定性适配故障需要最小修复外，不追加措辞/参数/新样本来寻找最好分数；旧失败和费用永久保留。

报告formation2例、later utility2例、temporary false storage2例、strict case4例、Host完成、原生额外开销、总质量—成本及失败链。无论结果正负，都不把系统级差异归因于SER，也不把外部自动摄取算作已经成功的内部F/R cue。

第二模型族端点仍未获得，保持NOT_RUN；本阶段推进可独立完成的外部系统工作，不冒称关闭该缺口。Product不迁移，总Goal不因一个外部系统小样本而自动完成。

- [x] 已固定源码来源、语义公平性判断及原四例范围。
- [x] 官方SDK适配、依赖和必要窄检查。
- [x] 输入/模型合同/源锁冻结。
- [ ] 两臂真实小规模运行、全部成本与语义结果。
- [ ] Failure Review、Reflection、复现和Luna发布。

源码已冻结为85文件 mapping `37e57b17808d9378111032de11ba66960280620586b1a2a9586e4e81aaffc4cb`。官方SDK假Provider验证4/4，默认B1既有2项、静态/边界检查通过；两臂使用同一Python3.12.11隔离环境，旧Python3.11环境未改。BM25快照缺少FastEmbed要求的`mock.file`和`tamil.txt`，已在隔离缓存补两个空兼容文件并明确记录；真实稀疏向量/实体连接/持久化已在假Provider路径验证。尚无v26真实模型调用。
