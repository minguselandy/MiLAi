# v13.2 公开任务准入与只读复现

2026-10-01。这是后续运行的输入与评分合同；新pilot、正式任务及v13.2四臂适配尚未运行。
E0门禁仍未通过，本页不准入D4，也不把已有公开任务开发结果称为未见结果。

MERIT使用已有作者仓库固定提交
`293933d96b1d1849e1f20d1bb324def5de9ed33f`。Root只读核对本地HEAD、干净工作树、
原12个声明文件hash，并记录当前13个Python文件的完整包闭包hash。
现有加载器重新生成已曝光seed0的五episode/seven-message完整arc，
与原冻结arc及初始world字节相同。五个原生checker对原初始world均为false，
checker前后world相同；0新arc、0业务mutation、0生成/嵌入请求、原账本字节不变。
见[限定准入证据](../data/manifests/v13-2-public-task-readiness.json)。
这证明原固定输入可重建；尚未检验新任务的最终原生checker、额外效果或语义忠实性。

旧MERIT seeds 0–64与原预留65–82继续排除；不回收未确认未曝光的预留任务。
新任务在完整核心与共同适配合同冻结之后，按metadata-only固定域、难度、来源arc及
模板家族清单登记，再生成完整原生arc。保留全部episodes及全部用户消息，
不按题长、输出、checker结果或是否适合当前方法筛选/替换。
新source commit不能仅靠改seed洗掉旧来源或模板曝光。

Host只能收到当前公开用户消息、合法此前消息、真实公开工具结果与方法实际交付的记忆。
隐藏world、checker_args、gold_fact_value(s)、未来episode与评分结果留在评测侧；
它们不能影响检索、来源选择、writer、修复或模型工具提示。
事前pre_satisfied单列，原生checker_after与原官方成功定义分别保留；
它们不能覆盖额外业务效果、错误字段/范围、虚假最终回答或缺失轨迹。
官方memory-utilized字面匹配只作其原指标，不冒称自由文本语义评分。

四臂必须复用相同公开工具、授权/发现、来源archive、一次普通交付、
metadata共同预算、实际追加读取及生成admission。
原生ADD/摘要/Host/writer/修复/索引与失败请求全部计入原连续账本；
12与24总生成预算保持独立cohort。
新的通用适配尚未实现；不能用旧runner存在替代其同能力验收。
业务schema仅以实际公开字段/效果合同适配，缺版本就保留最后观察/未知，
不得从隐藏world补造资源版本或当前事实。

MemSyco继续使用[来源amendment](../data/manifests/v13-2-source-group-amendment.json)
中的传递来源组件。Scope/Valid/Personalized分开报告；Valid未预留七行只有两组件，
不足以支撑充分独立的正式更新比较。最终任务规模与停止规则须由新的有效pilot
及真实来源/模板依赖在正式输出前冻结，不把旧117个预留成员重新标成未见。

官方确定性checker与逐字段检查只能接受它们实际检验的内容。
自由文本、范围、来源解释仍需冻结输出后的独立盲评分；Root复核为开发诊断。
独立审查者和第二模型家族目前不可用，相关结论保持未证实。
完整复现、正式精度、未见泛化及5pp非劣均未完成，Product仍NO_GO。
