# v13.2 实际结果集读取与保存回执的只读设计范围

本次授权同一既有Source owner在新的隔离checkout进行READ_ONLY方案审查。基础为已发布的Root `da33e6169c2745fbb50aee3f0a4370b9ceb1f02f`，212运行文件map `36338eb57ba458ceb5a02308c254d84615f1896535c6a1e1c0a802c369e798cf`。先由Root发布并精确核对本范围，再开始审查。既有所有树HOLD，不修改主开发树或运行源码；本范围不授权实现、实际cohort、配置更改或模型请求。原完整计划ACTIVE。

只读目标一：通用的ordinary和explicit-query结果集可以同时向模型返回合法分页指针。指针须解析到实际返回它的结果集，不能把另一结果集的omitted menu代入。检查`prepare_context`的存储键、结果集menu/hash和生命周期、`search_tool`/`recall_tool`、后续实际wire投影及`selected_page_tool`；只读解释现有路径，不消费真实实验记录。提出一个默认关闭、最小改动的快照绑定机制，使实际返回的指针能够读取该实际快照，并保留owner/bank/公开turn/selection、实际Source/版hash与权限检查。

只读目标二：实际读取协议拒绝需要诚实区分可恢复的公共工具错误与未知程序故障。提出有限typed错误来源和呈现路径，说明实际ToolNode/observer/边界传播如何保留原call ID、status、拒绝原因和已完成的旁路actions。不能用`handle_tool_errors=True`或广泛捕捉ValueError/Exception吞掉owner、预算、CAS、冻结漂移、SDK故障或未知程序错误；不将错误当成功、不自动修参/重检索/重放调用。需兼容实际安装的langgraph1.1.10/prebuilt1.0.13，当前文档≥1.2功能不采用。

只读目标三：公开保存承诺必须依赖已经完成的成功语义commit回执。静态核对Host tool成功、Host final与闭合writer生成/真实receipt的时间先后，区别业务成功、原事件/确定性观察保存和语义卡提交，提出领域通用的诚实回执/工具合同说明候选。不能改原最终答复、增加语义分类器/后验verifier/预执行reviewer或额外付费生成，不强制Host调用工具或按特定问句/任务路由。writer pending/partial/truncation继续显式保持。此目标只是方案比较，不宣称提示能保证语义正确。

所有候选继续一个logical MemoryService、原Store/journal、原公开schema和Source DTO；不新增平台/服务/数据库。原排名、选择身份及次序、查询、六记录限制、完整来源与角色/hash/CAS、typed直接writer、实际provider grammar均保持。Host12、ordinary2048/max6、writer1/repair0不变；所有注册/提示/错误说明及显式读取须进入真实成本，缓存不免费。不得自动替换cursor、从错误生成有效cursor、取全量、扩selection、挑更优Source、Source union、默认新源或用bank扫描寻找相似句柄。快照失效/撤销及无法确认身份要明确拒绝；只读Source需说明既有读版本边界和每个新增机械关系，不能声称蕴含验证。

允许读取的运行文件、工程测试、已归档官方方法文件及原件hash由[机器范围](../data/manifests/v13-2-read-protocol-proposal-scope.json)逐项列出。允许只做字节/hash、rg/AST等静态操作，记录真实命令/stdout/stderr/前后完整运行/测试/配置maps。全配置只可hash，不能读内容。禁止实验fixtures、rubric、scorer、实际cohort/ledger、benchmark/gold/holdout及未来问题内容；不能运行包、pytest、SDK、方法源码或第三方项目。新合成实验和执行审计器也留待Root具体实现授权。

官方资料只使用已存固定AIP158方法、固定LangGraph标签ToolNode及实际安装副本、官方设计页和已存provenance摘要；原字节/UTC/版本/hash保留。标签与实际prebuilt字节不同，不能假定同一实现。无需重新下载、升级或读取论文全文中的新任务数据；若缺方法资料，先提出需要的确切primary URL和理由，由Root归档。

交接提供原HANDOFF、file-index、完整真实命令回执/stdout/stderr/前后maps、所有失败、方案与否决理由、默认字节不变的拟验收矩阵、成本/材料省略压力及实际D0/P5/Host/基线/M/writer闭包的最小路径。标明哪些是静态观察，哪些是待验证推断，禁止将方案或工程控制升级为模型收益/泛化。交接后Source READY/HOLD；Root独立核对原件，再另发布具体实现范围和空树身份。任何下一实际模型cohort仍须重新准备、冻结、发布核对后首次执行，原R7不重跑，D4未准入、Product NO_GO。
