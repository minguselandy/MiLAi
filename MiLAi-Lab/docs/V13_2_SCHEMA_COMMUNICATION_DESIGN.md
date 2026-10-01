# v13.2 通用工具说明与真实结构反馈

Root接受只读提案作为下一隔离工程的输入。新候选为默认关闭的`tool_schema_communication=shape_feedback_v1`，联合改变公开参数说明、真实结构错误反馈及trigger元数据/Source正文措辞。尚未实现或执行机制检查；它不代表来源语义修复、单因素收益、泛化或D4准入。[机器范围](../data/manifests/v13-2-schema-communication-scope.json)与[R6完整结果](V13_2_E0_R6_RESULTS.md)分别记录设计授权和实际失败。

R6原24轨迹/48消息保留：21任务通过/3失败，正常22门槛未过；5轨迹/6版本仍有直接支持缺口。工具外壳合法不能证明内部参数合法，合法来源成员不能证明支持新断言。此次研究的论文、固定官方项目及未采用候选均已保存于[资料库](V13_2_DESIGN_LITERATURE.md)，不移植上游成绩或benchmark内容。

## 原始只读交接与Root核验

Source提供280个索引原件、48条真实subprocess回执；47返回0，首次定位不存在的`agents/`返回2。前11条保留原17文件map，后37条保留19文件map，不追补原缺失覆盖。最终14运行源码/5测试map为`d21e7f35917cf756746e49e88f5c55d3ae567f84a4f0bd2fad923e8421123226`；Source提供的全211身份来自先前接受原件，本轮Source未重读全量。初始/末次观察HEAD为6dfa313/5ef0ee0，Root后续c3ffd5b只发布结果/资料，运行身份未变。

Root逐hash核对280原件、48回执/stdout/stderr/全部原maps、19源码快照及9已归档参考原件，连同索引和FREEZE精确复制282文件到`artifacts/v13-2-schema-communication-proposal-source/`，原Source文件及provenance-notes保持。Root独立重新hash211运行文件，仍为`8c466d3ca839ea0db5aaa722ae20ffa6c11460c8f1d5c068e53921b6cb6551ce`；连续账本前后仍`73c437acc68e2e6e7a04b0d9ecb9ff3353936769f0d9c7bec4d40566dcbd2df1`。此次核验0新增模型HTTP，不执行Source审计器或上游项目。Source关于无SDK/网络/数据访问的范围声明保留其实际命令与instrumentation限制。

只读HANDOFF SHA为`6773f8295755d6caa56d6834a832d4f7a4f5d67cf6450f40e5d43cb62f7f3809`，manifest为`b3acdc2b3640b3e380e379c914483e4653fd0cb89d7df638de871796189bec4f`，file-index为`2a84570570a206212246790785c169fc57cc5e00de0cd03c58a55d2d8cbeb4cb`。Root原核验器/首执行日志和新回执在`artifacts/v13-2-schema-communication-proposal-root/`及`artifacts/v13-2-root-drivers/`。两次Root只读路径/解释器查阅失败保留工具来源与缺少当时map的限制，未改实验或源码。

Root首次inline范围元数据脚本因缩进错误在解析阶段失败，语句未执行；原工具输入/返回码/错误来源另存，不伪造原磁盘脚本或当时map。独立文件版首次执行返回0，范围和D4草稿仅追加候选，运行源码/账本再次保持。

## 限定实现

新增纯helper`contracts/tool_schema_communication.py`，仅读取当次实际公开catalog与真实已捕获异常，不读Store、候选或Source。其余范围限定`providers/chat_bridge.py`、`baselines/langmem_agent.py`、`methods/langmem_recipe.py`、`methods/grounded_memory.py`、`runners/v13_1_d0.py`及`runners/v13_1_p5.py`。测试新增`tests/unit/test_tool_schema_communication.py`，有限扩展两个现有schema/direct-support测试。若实际入口需要超出范围，先静态说明依赖和最小新增路径，Root另给具体范围。

普通Host/基线/M共享同一显式接口，recipe、实际D0 prepare/catalog/freeze/runtime与P5 live/resume完整透传。省略/显式legacy保持原catalog、wire、文字、错误、状态逐字节一致；未知flag或冻结漂移须在dispatch前拒绝。实际工具schema、generation free-object grammar与参数不变，说明副本单独记录呈现SHA，原校验schema单独记录原SHA。

公开完整JSON形状明确实际`content/scope/basis/kind`与四字段`field_support`对象的层级，revise值位于`semantic_patch`，支持说明为其兄弟。placeholder明确不能执行，不给真实业务值/Source ID；外层来源由模型显式选择，不能程序union、补源、coerce、改写参数或默认current。整字段复用只解释原实际读句柄、完整严格等值与原叶集要求，不增加机制或伪造子句归因。各方法只解释它确实拥有的公开参数。

区分三类真实错误：共享`build_agent`原JSONSchema拒绝只呈现实际arguments根的绝对path/schema_path、keyword和已公开约束；真实Pydantic拒绝只呈现原loc/type；Service receipt保持原reason。optional carrier遗漏由Service拒绝时不能伪称JSONSchema required。路径/context有固定小型上限和明确omission/hash，保留原父子关系；禁止instance/message/repr/stack、任意schema全文、未交付业务expected或自动best_match分支选择。原工具name/call ID/status与pending/partial/已成功action保持。

新profile在实际catalog说明副本、普通packet policy及writer support_policy三处澄清：trigger_binding元数据证明回合身份/维护授权；同一真实Human Source正文若表达事实，仍可由模型自由选择支持。问题自身不证明旧值。当前机制本就允许当前或历史叶，不能描述成禁止当前Source，不增加问句/关键词/语种分类或语义verifier。新增packet文字须进入实际packet hash及2048成本，原Source/角色/hash/CAS/DTO保持。

Host12、ordinary2048/max6、writer1/repair0、共享连续费用账本、原排名选择及所有历史root保持。完整请求中的catalog/protocol/错误反馈另计真实Qwen tokens和paid prompt，不能把packet之外文字称为免费。writer保留原typed直接invoke，新增JSONSchema preflight、付费repair或重读均不在授权内。cap拒绝trace仅单列设计缺口，此工程不实施admission/budget/HTTP可观测改动。

## 工程验收与后续实际实验

只在新隔离树、发布并核对本范围提交之后，由同一既有Source owner实施。保存每次真实命令/失败/stdout/stderr/前后source-test-config maps、原审计器版本和阶段SHA。既有所有HOLD树不改；Source不读配置、案例、rubric、scorer、gold或holdout，不操作全局账本，不进行实际模型/embedding HTTP、SDK升级或部署。

有限检查覆盖真实D0 Host/ToolNode与writer MockTransport、P5恢复漂移、通用基线接口、参数层级与任意公开合法值、实际三类错误来源及恶意/超长内容安全编码、同Human支持叶可选、原CAS/owner/replay/receipt、不额外writer或退款。采用现有实际本地Qwen tokenizer，合成局部账本、禁socket，记录完整请求和ordinary压力范围/省略代价；省略/legacy与冻结旧源码的四组合默认wire实比较。执行相关ruff/mypy和package/tools两边界，不扩大成无关旧探索回归。

Source交接后Root独立验收原件与受影响机械checks，才转入主开发树。任何实际后续cohort须Root另冻新配置/route/runtime/工具/原rubric/原连续账本和空root，发布并核对冻结后按原完整24/48首尝试串行运行。任务、真实送达、结构、来源语义、授权和费用分别报告，不择优拼接、不重跑旧root。完整计划ACTIVE，D4未准入，Product NO_GO。
