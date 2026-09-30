# v13.1 类型×scope 开发诊断

状态：R2因素工程检查PASSED_SCOPED，语义结果PARTIAL；未证明类型独立收益。
完整P0–P8仍ACTIVE，Product NO_GO。

四个已曝光contextual_scope_control案例按预定ID哈希排序选取，不根据问题/成绩筛选。
[公共输入](../data/fixtures/v13-1-p4-type-scope.json)完整保留过去role/event ID/content。
四臂Flat、Type-only、Flat+Scope、Type+Scope共用模型/prompt/闭合形成边界，writer只见历史，
不见后续问题；所有source_refs只可选公开历史ID。相同SDK SqliteStore分别持久化，新reader进程
实际重开后读完整bank；材料6000实际token、输出4096、不静默截断。每案例臂1付费writer+1付费reader，
all-delivered用于区分形成与消费，不是ordinary retrieval或完整候选Agent替代品。

[首轮](../data/manifests/v13-1-p4-type-scope-r1-results.json)16形成/16读取完成，但开放scope对象
让Flat+Scope写入kind/type分类；不能作为清洁因素对照。部分bank还在12条记录上限下遗漏最后情境。
原始提案、bank、answer和费用全保留。32generation/51011tokens，没有embedding。

[R2预冻协议](../data/manifests/v13-1-p4-type-scope-r2-protocol.json)将scope公开字段收紧为
subject/group/project/event/context/time/exclusions，与semantic/episodic组织字段分离，未知允许null。
模型仍提出scope，不填gold或改正文；四臂共享追加的scope定义提示，其他预算和输入相同。
该提示也改变Flat形成，所以R1→R2不能归为schema单独的因果收益。

[R2实际结果](../data/manifests/v13-1-p4-type-scope-r2-results.json)16形成/16reader/32不同进程完成。
独立SDK再读全部bank，实际HTTP确认writer输入精确只有历史、reader精确消费SDK材料。
所有16个bank保留最后情境，ID/列形状/材料容量及foreign namespace检查通过；内容和scope真值仍unchecked。
完整原源、输出固定后才读取四个原官方evaluation rubric，Root逐项语义审查；无模型Judge，
不冒充官方发布分数。预定任务标准和额外来源归属错误分开，不以关键词命中作结论。

| 表示 | 通过 | 失败 | 未知 | 分母 |
|---|---:|---:|---:|---:|
| Flat | 2 | 2 | 0 | 4 |
| Type-only | 2 | 2 | 0 | 4 |
| Flat+Scope | 3 | 1 | 0 | 4 |
| Type+Scope | 2 | 1 | 1 | 4 |

雨衣情境四臂都按通勤可靠性/维修与生命周期价值限制最低价默认，仍保留不要多余功能的偏好；
onboarding四臂都明确给新人解释异常审批原因，而不只列动作。定价情境只有Flat+Scope明确保留
并使用旧/新总价比较所需背景；其他臂泛用记笔记框架、被动等待或未知。junior mentoring四臂
都把用户自己接受直率批评的偏好转给紧张初级同事，未按接收者情境调整。

另保留真实ID旁的错误来源归属：assistant-only建议被写成用户意图，例如Type+Scope mentoring
memory-0004，Type-only onboarding memory-0003/0005/0007；这些不是引用存在检查能证明的语义。
完整事实可靠性不能由上表task维度通过率推出。消费中的scope迁移和bank遗漏不准入Attention。

仅4个已曝光开发原始场景，模板相似；不计算研究置信结论、不宣称未见泛化。
Type-only未优于Flat；Type+Scope也未优于Flat+Scope。该结果不给双类型结构独立贡献。
后续研究如仍讨论类型，须在冻结强简单控制和新样本上验证，而不能改写这轮负结果。

R2新增32generation/51288tokens/0embedding；两轮共64generation/102299tokens。
逐个真实response与原连续账本精确核对，最新6511generation/12004306generation tokens/
420830embedding tokens，unknown0。SHA256
7e43b6a2e16f80494c0bc90cafdb8fb8c30120e92d41de77d7d12e7993bd99ca。
每阶段wall/CPU、SDK重开、实际文件与材料字节记录；总Store I/O仍partial。

本轮在cda98ea独立冻结工作树运行，200个runtime源文件与原fda8672相同；P5源码负责人同期
只在主开发树进行无HTTP修改。没有混用变化中的源，也没有并发模型调用。
