# v13.1 文稿审批与发布开发轨道

2026-09-30。源码机械验收通过，实际模型质量尚未运行；完整目标 ACTIVE，Product NO_GO。

第二工作流使用真实 SQLite 文稿、内容版本／摘要、独立审批和指定受众的发布记录。
编辑使旧审批失效；审批与发布均校验实际当前版本／摘要，原历史保留。发布记录是 sandbox 内实际持久化产物，不代表向外部受众送达。
原预订／标签工作流仍是默认；新工作流通过 `application_workflow=document_publication_v1` 启用。

用户给出自然标题、完整正文和受众。工具公开提供实际版本／摘要；共同保护层只绑定真实同对象回执，正文和受众仍须与授权相符。
正常发布可以直接使用实际审批回执；UNKNOWN 重试才要求独立当前查询证明。同一业务 journal、Source、MemoryService、Agent／checkpoint 处理三个真实退出窗口，没有新增长期事实系统。

Field-grounded 的可选文稿合同只检查八个字面字段：status、document_version、content_digest、approval_status、approved_digest、publication_status、published_digest、audience。
版本必须是整数，不能用布尔值或字符串替代。正文 JSON 的字面声明与字段、实际公开回执一致；可选 notes 保持未验证。Ref-only、B6 简单投影和字段视图关闭仍按各自边界声明，不推导全文真实或当前操作适用性。

[源码验收](../data/manifests/v13-1-document-source-acceptance.json)包含完整209文件联合身份、208文件比较身份与检查日志哈希。
文稿／共享24额度机械13项、四臂零HTTP准备1项，以及实际安装 Mem0 SDK 的关闭顺序2项通过；后者在真实临时 Qdrant／SQLite 与网络拒绝条件下执行。
回归首轮133通过／2失败／3可选 native 跳过，两个失败目标修正后各通过；跳过不计通过。首个红测、静态错误和原付费快照失败均保留。
两份 CI 与 canonical matrix 同步。上述证据不代表抽取语义或模型质量通过。

[事前输入](../data/manifests/v13-1-document-development-candidates.json)声明六个开发故事、四个主臂、原生维护节奏、有限视图消融和单列 Mem0 手动 UPDATE 扩展。
质量设置对所有臂共享24次生成额度，Host／writer／native 及重启共用持久 admission；联合12次预算另列，全部沿用原连续账本、并发1。
24次设置在看到任何文稿模型输出前确定，用于容纳真实查询、正文恢复、重新审批／发布及计费形成；不能把旧12次失败重称通过，或声称每个 clean 必须24次。
共同提示中的不支持操作处理同样在文稿输出前固定，原预订提示及失败保持原样。

实际运行前另冻完整源码、CLI、环境、输入、提示、schema、时序和评分合同。协作者编辑由真实后端事务发生，之后的公开查询才成为 Source；注入标签、预期终态和控制文件不进入 Host／writer。
六个开发故事不能替代12个新 Pilot-L 或两个工作流各30个正式基础任务；正式规模、模板敏感性、独立 Judge 和第二模型家族要求仍保留。

运行前另发现原生输入载体把当前已观察到的用户／工具事件标成完整对话。
[后续载体补丁](../data/manifests/v13-1-mem0-observed-carrier-source-acceptance.json)将比较器显式设置为 `observed_events_v1`，保留原始行和原生 ADD 抽取算法；旧默认载体保持原样。
实际安装 SDK 的两个网络拒绝／MockHTTP 检查、九个受影响边界检查及静态检查通过，只证明机械路径。
此前2672373版本的完整源码身份、零调用准备和首个预检错误保持原样；新补丁尚须另冻完整 Source／CLI 后实跑，文稿模型质量仍 NOT_RUN。
