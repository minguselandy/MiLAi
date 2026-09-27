# WP5：同粒度整体更新与普通patch

状态：设计收敛，输入与评分已冻结；源码实现、必要检查及终版构建已完成；四条真实一次提案诊断已完成并评分；实际CI按后续独立记录。依据[计划§8](MILAI_NEXT_IMPROVEMENT_PLAN_20260927_v1.0.md)
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

## X2实际结果（5874ca4，2026-09-28）

[PR58](https://github.com/minguselandy/MiLAi/pull/58)发布head
`5874ca4ffbf7c08cfb8c4bf8f3108c9b9700696c`，base为07aaa3c；独立detached源码执行，未合并main。
[正式冻结](../data/manifests/next-improvement-wp5-local-update-freeze-20260928.json)的prepare identity为
`c755db0f1bde4b852a9d4eebe44510ba530d1f7207526f64bab15c649a80198e`，freeze SHA为
`6659c34bcf16b3e70c13c86ff2c4eafa0dece749a52df9bd5fe49ce7ae073858`。
[逐例实际结果](../data/manifests/next-improvement-wp5-local-update-results-20260928.json)保留每次提案、真实回执、
State读回、pending和费用。四条均实际HTTP 200/usage已知，没有新业务调用、Host回答或embedding。

| 前缀 | replace | patch_or_replace | generation tokens：replace / patch配方 |
| --- | --- | --- | --- |
| 只改访问时间 | 正确，原ID revision1→2 | 正确，唯一完整句patch，revision1→2 | 1452 / 1507 |
| 实际预订成功但标签失败回执 | 正确，revision2→3、实际ID/失败结果/待办正确 | 拒绝，选择replace回退但误撤非现有链接，零State写 | 2015 / 2168 |

整体重写2/2，patch配方1/2；三个成功提交均保持原精确计划、包装、门位及对应时间，原来源未删除。
局部patch成功后的完整正文与replace完全相同（除本轮引用集合不同），并非只检查一个数字。
部分回执成功例记录了实际reservation ID和标签未创建，清空原待执行预订，未丢失访问安排。
这是一条已暴露arc的两个构造前缀、四次一次提案Store诊断；不是四个独立样本或完整任务成功率。

## 拒绝原因与决定

Observed：失败臂选择了允许的整体重写回退，正文和needs提案合理，但remove_evidence包含初始用户来源。
该来源在合法source catalog中存在，却不在当前revision2 State的evidence_refs内；
程序按冻结的“撤回已有链接”合同拒绝整条更新。State正文/revision完全不变，待处理ToolMessage仍pending，
State bank put计数相对seed没有增加。保持旧内容不能抵消必要更新未完成。
Expected：提交实际预订/标签失败结果、解除旧待办，并保留无关信息和正确来源链接。

第一断点在提案选择了未绑定的来源链接；它没有尝试literal patch，不能归因为patch匹配器坏了。
两个解释是：模型混淆“可见来源”与“当前已绑定来源”；或者对已不存在链接采用严格拒绝增加了接口摩擦。
后者可以是另一合同，但不能在看过结果后放宽校验改写本轮成绩。实际HTTP原文与执行calls一致，
同前缀两臂material payload逐字段完全相同，排除了材料分叉或parser丢字段作为这次原因。

决定为Pivot默认局部维护优势主张，保留可选普通patch接口，停止增加变体或反复提示调参。
X5在没有新证据前继续简洁整体正文路径。若以后实际任务确需拒绝后修复，须对两臂另冻相同真实错误续接机会；
本轮一次提案协议不追加修复，也不据未修复结果否定所有patch用途。

## 完整费用与适用边界

replace两例合计3467 tokens（2863输入/604输出）；patch配方3675（3097输入/578输出），
多208，约6.0%。局部例虽少输出62 tokens，但多输入117，合计反而多55；大schema开销已计入。
部分例是replace回退，不能将其成本解释为“短patch”效果。没有节约信号或维护质量优势证据。

新增4次生成/7142 tokens，全部control；0 embedding、0 Judge、0新业务执行。
实际生成HTTP wall合计8.523396秒。连续账本为2799次生成、3486504 generation tokens、19273 embedding tokens，
SHA `bfc2768c4cd6d92ce650bc65e2018b8d23a404de0c9a61e07e88ccbd1c43d0c6`，历史链逐字段未变。
State种子index=false，trace确无embedding，不是漏记后补零。Store读写/CPU/wall/逻辑字节包含seed与观察，
详见逐例记录；不是物理I/O，也不代表形成加多次复用的生命周期成本。

复现使用该commit的`tools/run_state_update_probe.py prepare/run-job`、公开inputs/config、原ledger绝对路径，
注入ignored DSN，新隔离run/namespace，四job原顺序串行且每个只一次提案。rubric不进入运行时。
原失败attempt不可重放替换；新合同或重试预算需独立冻结并披露曝光。
