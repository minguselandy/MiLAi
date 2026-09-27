# WP5：同粒度整体更新与普通patch

状态：设计收敛，输入与评分已冻结；源码实现、必要检查及终版构建已完成；发布后执行identity待冻结，真实实验尚未运行。依据[计划§8](MILAI_NEXT_IMPROVEMENT_PLAN_20260927_v1.0.md)
和[执行Goal](MILAI_NEXT_IMPROVEMENT_EXECUTION_GOAL.md)。不覆盖C3a及历史D0合同。

## 首断点与可比较范围

当前bank.apply要求完整content；局部变化仍须生成完整正文。H1：重写范围使无关内容易丢失；
H2：错误在语义选择，局部接口仍可能改错对象/值或漏掉跨句变化。
两个解释未被现有工程检查区分。Root就第三候选是否独立这个具体设计冲突请求Astra分析。

设计决定：收敛为两臂——相同事项粒度、相同完整前态下的整体更新与强普通patch。
expected_revision加唯一old_text/new_text本身就是普通patch，当前没有独立的第三算法。
候选局部表达与普通patch合并，不复制等价实现，不通过拆小candidate记录或削弱baseline
接口制造优势。若有收益，归于局部编辑接口；不声称额外机制创新。

## 最小待实现合同

现有State字段不迁移。既有对象更新可显式带id、expected_revision以及replace/patch模式；
replace提供content，patch提供若干old_text/new_text，两者互斥。两臂共同验证目标版本。
旧调用缺省保持原合同；新X2两臂独立冻结版本检查，不能把它单独归为patch优势。

每个old_text必须非空、在同一目标版本原正文中精确出现一次；各片段互不重叠，先全部验证，
后一次提交。允许空new_text删除片段；插入用带唯一上下文的替换表达。不模糊匹配、
归一化或猜第几个命中。版本过期/不唯一返回真实冲突，不自动猜修复。多个patch可以
表达跨句变化，必要时允许核对后的整体重写；实际选择方式须计入结果。

省略title/needs仍保留；evidence为新增引用，remove_evidence为明确撤回已有链接，
增删集合不得相交。两臂共用这些能力。保留引用是继承谱系，不称本轮重新审阅；
撤回链接不删除原来源，也不减去机械依赖元数据。合法ID不能自动认证语义支持。

实现优先在既有提交路径加入纯转换/校验函数，再复用长度、revision、依赖和持久写入。
单条State的多个patch全成或零写；不同State仍可部分成功，不新增两库事务或journal。
基本scope/参数检查后，先识别已提交D0槽位，再做版本/片段/引用变化校验；否则成功重放
会因revision增加或旧片段消失错误失败。replace/patch共用原update:slot身份，
不因换表达模式而重做同槽；原event_set、batch、slot、ack合同保留。
这只是串行读取后检查，不是跨进程CAS；同文新事件仍为新事件，语义一次消费继续未证明。

## 拟定最小X2（尚未冻结）

两个前缀×两臂，各一次提案和隔离真实Store执行；不展开大矩阵。

1. 局部正例：一个事项内有精确名称、数量和多个独立约束，新事件只改一处。两臂交付相同
   完整前态，不给patch预选正确片段；同时检查必要改变和无关保持。
2. 反例：实际部分成功业务回执要求同时更新状态、实际结果与后续待办，原约束继续保留。
   允许多片段或整体重写；只改一个易匹配位置而漏掉必要更新仍失败。

第二项优先复用WP6续接产生的真实合成世界回执；在实际回执出现前不伪造业务ID或成功。
错版本、重复片段、恒等patch、同槽重放及同文不同事件用必要机械检查，不增加模型矩阵。
writer policy、时点、模型参数、来源权限和事项粒度固定；所有schema、匹配文本、重读、
错误、回退和观察费用都记入连续账本。拒绝所有修改不能算保持成功。

若patch完成必要改变且减少无关破坏，Continue局部接口的有界用途；若仍选错/改错/漏改，
Pivot具体语义选择问题，不继续叠加patch变体。两前缀不是统计胜率证据；即使通过，
也不宣称整体方法或语义一次消费已解决。

## X2输入与评分冻结

[输入](../data/diagnostics/next-improvement-wp5-local-update-r1/inputs.json)、
[配置](../data/diagnostics/next-improvement-wp5-local-update-r1/config.json)、
[独立评分](../data/diagnostics/next-improvement-wp5-local-update-r1/rubric.json)已冻结。
局部前缀是在旧实际revision1 State上构造一条新的访问时间修改；部分成功前缀保留旧实际revision2
State及合法历史，加入WP6真实正确动作轨迹的工具回执。两者是一个已暴露arc的构造前缀，
不是未见任务，也不伪装旧轨迹自然连续。输入不含评分gold片段或之后的Host答案。

WP6回执取自`3-partial-raw_sources`的ec34c89方法，结果SHA为
`9ee89f1f614a4008ebdd6c551806043d478ec5e4262febec6100828728fc9fe9`；精确业务ID和ToolMessage来自实际
SQLite写入与真实工具执行，未重新执行业务。该回执在本X2中是固定合法观察，各臂完全相同。
每臂一次维护提案及实际State提交，格式错误、拒绝、空提案均保留；不把本诊断当完整回答或动作成绩。
模型配置沿用已冻结服务，两个臂都用2048 control输出上限，所有输入/schema/patch/结果费用分别记录。
正式源码、schema和执行identity将在实现完成后再冻结。

## C4工程冻结

[检查回执](../data/manifests/next-improvement-wp5-local-update-checks-20260928.json)记录8文件源码/CI身份。
新窄测12项、相邻State/writer策略95项通过，目标Ruff/Mypy、150源码归属矩阵、两边界及diff/EOF通过。
包含单State零写拒绝、同槽跨表达重放、不同事件、真实executor、原来源保留、跨State部分成功，
均为mock或InMemoryStore工程证据，无真实Host/embedding/共享Postgres调用。
协议/controller/既有职责配方未改；默认factory继续旧schema，新版本/patch合同显式启用。

预发布四job零模型prepare身份`39055f7a68b40ef61051b48e0864c0c44851ab28cc6aafe0abd39b5b5582be98`，
不是正式执行身份。仅一次必要离线构建：wheel
`e31fcd8a194c02678134f82f8e4aea11e6f6452441bf8db222d9a44fa8d18081`，sdist
`ffc8a5e5f6285aef7aef635e58e0fc761da891c22df4ae70f022839874a66516`；
新CLI/输入包含、私密artifacts与环境排除已核对。本工程回执与本段是构建后补齐元数据，
不声称之前分发包已含这些文字，也不为纯元数据再构建。正式运行在发布后的detached源码重prepare。
expected_revision为串行读后检查，不是跨进程CAS；局部patch不证明语义正确或事件只消费一次。
