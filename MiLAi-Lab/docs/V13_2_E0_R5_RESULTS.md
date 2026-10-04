# v13.2 E0 R5：完整开发复核与来源缺口

2026-10-01。[完整逐轨迹结果](../data/manifests/v13-2-e0-r5-results.json)记录独立新根目录的24条轨迹、48条消息；全部首次尝试完成，48个最终回答均关联实际原始HTTP响应。按原冻结rubric，Root完整断言、历史、scope、实际业务与持久状态复核为24 PASS、0 FAIL、0 UNKNOWN。正常任务22/24门槛限定通过，**完整来源语义门槛和两旧更新的完整门槛仍未通过**，D4仍未准入，Product仍NO_GO。

本轮只改变紧凑材料profile；共享表示、真实token成本的正文分配和新冗余正文hash省略一起变。R4的Host/writer提示、原输入/rubric、bank_prefix、12次admission、4096输出、temperature0、普通2048 tokens/6 identities、单writer/repair0保持。运行Source提交65140126、209文件map676ad5dc；[运行冻结](../data/manifests/v13-2-e0-r5-runtime.json)与[事前设计](../data/manifests/v13-2-e0-r5-design.json)保留原字节。报告冻结提交49a7288不是运行Source提交。preview和R0–R4没有重跑或拼接。

## 原任务与附加门槛分开

| 检查 | 本轮证据与结论 |
| --- | --- |
| 保存4条 | 对应实际卡、真实user来源及持久commit/reopen；4通过，无虚假已保存回执 |
| 召回4条 | 新进程接收实际有界材料，回答正确；4通过。邮件查询的多余维护被拒并保持pending |
| 更新4条 | 原卡同ID r1→r2、实际更正来源、原历史保留、无偏好副本；当前/旧值均正确，4任务通过 |
| 范围4条 | 不推断长期个人素食/私人预算，不扩大本次演示范围，不猜Friday绝对日期；4任务通过 |
| 对象续接4条 | 各一次精确授权预订、原身份和created标签，无重复业务尝试，回答符合实际回执；4任务通过 |
| 进程重启4条 | 原父进程回执、不同实际PID、同持久资源、实际材料消费；4通过。笔记查询的冗余修订被拒 |
| 两旧更新核心 | 语言和单位均同ID真实修订且正确读当前/旧值，限定通过 |
| 两旧更新完整来源 | 查询后r3仅引用当前问题，未直接引用原r1/r2支持叶子；未通过 |
| 全部来源语义 | 7条轨迹存在当前卡直接支持缺口；未通过。来源成员/hash核验不能代替蕴含判断 |

任务分数保持R4的同一复核口径：R4语言查询虽然有问题引用的r3，原声明更新/历史/最终任务仍PASS，来源缺口另列。R5的24 PASS同样不表示每张新增/修订卡的完整来源归属都通过，也不洗掉后续维护失败。

四更新查询首个真实HTTP包均在2048内送达完整当前r2和完整历史r1；此前R4均只有当前正文。每包实际选择1 current、1 historical、4 Source；送达1 current、1 historical和1截断Source，省略3 Source。叶子全文没有因此自动送达。会议查询又显式读取r1/r2，其余三条直接回答；构造、送达、读工具与最终语义消费均分别记录。仅四条曝光开发查询的送达改善，不能归因纯压缩、宣称单因素因果收益或一般历史消费率。

## 当前来源缺口与保留的失败

四个更新查询均再增r3，内容正确却只绑定当前问题。支持当前/旧值的真实user叶子仍在各自r1/r2历史里，但没有成为r3的直接支持。这是语义来源缺口，不是旧历史丢失、错owner或虚构当前/旧值。

范围1正确回答不应默认个人长期素食，并显式读取原始否定陈述；Host随后新增“无固定素食偏好”卡，却省略source参数，由当前事件默认绑定到问题。卡的否定事实被旧原文支持，实际新卡的直接引用仍不支持它。本轮没有新增错误的正向个人素食事实，不能据此忽略负向事实的归属缺口。

对象1/4续接writer分别将同ID修订为r2，绑定新的get_reservation。它可支持当前created状态，却没有直接证明卡中保留的“曾预订并制作”历史操作。原r1和真实reserve_and_label源仍保留；实际业务各一次且未重做。任务通过与当前卡的完整历史归属分开。

维护总计25 skipped_host_committed、10 no_change、6 committed、7 pending。四个对象第一消息的额外writer把object_ref生成dict，实际schema要求string，因此ValidationError；Host此前真实卡已经commit，没有补发、重试、修复回答或把pending当成功。其余pending为邮件/项目预算查询source_selection_required，以及笔记查询current_boundary_source_required。全部原响应、费用和拒绝原因仍保留。

## 独立SDK重开、HTTP与费用

真正针对R5的只读SQLite SDK重开24个库、404个条目，与最后实际回执一致，数据库hash不变、0mutation。95个实际Host HTTP的完整当前packet、current Source role/owner/hash、selected inventory与版本身份、普通材料和当前recall引用的联合Qwen token预算均核验通过，最大2048。48个最终回答与原HTTP响应关联。该wire检查与构造日志比较版本身份，SQLite重开另检；二者都不自动证明自由文本蕴含。

| 费用 | 请求数 | 已知tokens |
| --- | ---: | ---: |
| Host | 95 | 402,845 |
| writer | 23 | 89,833 |
| 全部生成 | 118 | 492,678 |
| embedding | 50 | 20,507 |

逐trace与唯一原连续账本差额一致，新unknown0。累计8,860 generation／23,606,497 charged／23,576,110 known，历史unknown1及保守30,387仍保留；embedding881,362、unknown0。R0–R5新增914 generation／3,265,459 known和390 embedding／164,174 tokens。R5末账本SHA26f46d5fe3aeeaf0e399587098311e6d15bfacf01a0f231aca759207e6b0398b；不宣称降低费用、美元或GPU收益。

Root离线后检第一次脚本组装发生SyntaxError，尚未导入/检查或改变运行状态；原件保留。第二次命令错误指向R4 SDK重开，并把24库/407条目误报为R5。完整脚本、原结果/log/hash另存postcheck-wrong-r4-target-retained；纠正为R5后增加cohort身份断言，得到24库/404条目。R5真实模型运行未重做，原wire/collector结果也保留。此前Source前缀range审计假设错误的校准失败仍保留。错误审计结果不计模型成功或失败样本。

## 失败反思与下一步

重新查阅并保存指向既有原件的[设计资料与方法总结](V13_2_DESIGN_LITERATURE.md)。旧支持叶子存在不代表当前卡已经正确引用；触发当前边界和支持语义主张需要不同职责。下一修复候选继续用同一Source/MemoryService、模型选支持源、读时版本/CAS和真实pending；须显式保存模型选中的实际支持叶子及未改断言的来源关联，不能用问题关键词、案例ID、自动补最新源、语义verifier或禁用全部维护来换通过。

共享生成admission持久化另在隔离树HOLD，尚未接受/转入；全HTTP串行闭包只有只读调用链审计，未执行并发故障。B6摘要、共同reader/cache、形成节奏、Host写权限和四臂12/24实际闭环仍需实施与验收。本轮没有第二模型家族、独立Judge或未见来源验证；Root结果仅曝光开发诊断。原完整v13.2规划保持active，D4/D5与泛化仍未完成。
