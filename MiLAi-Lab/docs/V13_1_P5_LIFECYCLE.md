# v13.1 P5 真实恢复开发检查

状态：源码机械验收 PASSED_SCOPED；实际模型首轮 PARTIAL。完整 v13.1 目标 ACTIVE，Product NO_GO。

[冻结协议](../data/manifests/v13-1-p5-lifecycle-micro-protocol.json)安排六个开发案例、18条公开消息和22个子进程：W1两次、W2一次、W3一次真实 SIGKILL 后以新进程恢复。所有实际模型调用继续记入原连续账本。故障时点与后台可用性变化只由驱动使用，评分规则仅用于离线审核。

原始缺失回执的调用保持 pending/UNKNOWN；恢复另行执行公开状态查询。只有目标一致、实际查询证实标签不存在且公开请求仍授权的情况下，显式恢复合同才允许完成剩余标签。该合同依赖隔离 world 的无删除、单写入者条件，不支持外部并发业务的普遍 exactly-once 主张。

记忆提交后的重放按原始 tool call ID 与完整原始请求返回既有回执，避免重新解析当前 revision 导致伪冲突；修改原始请求仍被拒绝。此行为显式 opt-in，旧工具默认合同保持不变。

源码负责人保留全部初次失败。最终17项检查通过，包括真实子进程硬终止、SQLite重开、W3 UPDATE重放、共享同条消息预算与新消息独立预算；12项受影响回归通过，Ruff、严格mypy和验证矩阵通过。这些检查采用脚本模型，只证明机械行为。真实模型结果、实际提案/副作用、历史保真与完整失败分母将另行填写。

六案均使用同一种预约/标签工作流，不构成计划中正式生命周期的两工作流、60基础任务证据；P3近邻比较、P6 pilot与P7/P8仍须继续。

[首轮实际结果](../data/manifests/v13-1-p5-lifecycle-r1-results.json)保留六案全部分母：18条消息中7完成、4耗尽同条消息12次调用上限、7因前置失败NOT_RUN。实际13个不同子进程；W2与unknown-effect-happened的W1真实硬终止，后者在恢复后耗尽预算；unknown-no-effect的第二W1与W3 UPDATE因原始保存失败未运行。

clean与partial三条消息链完成，实际同一record UPDATE保留历史；只能报告两案的受限业务字段成功。clean还接受了无证据的2025过期日期，不能声称整条记忆真实。其余四案首断点为模型持续提交非JSON正文，拒绝回执已实际出现在模型输入，全部失败提案保留。unknown-effect-happened的原始标签调用仍pending/UNKNOWN、缺失原回执，独立恢复查询真实观察标签已创建，未重做标签；但最终修订/回答未完成。

Root以公共SDK重开六个实际数据库核对bank/source/rejected attempts/world和owner隔离；所有已提交历史revision的两个业务字段都与真实Source一致。六案均仅一个目标正确的预约，无错误业务副作用。73次实际生成、300,948 tokens全部与原账本核对，embedding新增0，unknown usage0，Judge0。完整账本增至6,584次生成/12,305,254生成tokens/420,830 embeddingtokens。

下一步只增加一轮单独冻结的通用JSON正文说明；源码、guard、工具catalog、模型、上限及六个开发身份保持一致，以新隔离资源执行，继续原账本。首轮失败不会改判，提示改变不能归因为恢复架构的收益。

[通用格式诊断R2](../data/manifests/v13-1-p5-lifecycle-r2-results.json)已完成全部计划分母：18条消息中12完成、3耗尽预算、3NOT_RUN；实际18个不同子进程，W1两种实际效果与W2均真实硬终止。clean完整链通过受限字段检查；partial与known-no-effect完成回答但未保存记忆，另三案未完成。因此完整生命周期只有1/6受限成功，不能用12条完成回答宣称整体提升。

unknown-no-effect恢复实际查询标签不存在，再按已授权的有限合同成功补标签；原始丢失回执仍UNKNOWN。unknown-effect-happened不重复标签。两者都因记忆提案失败而耗尽后续预算，最终回答未完成。所有六案业务对象正确且仅一次预约，没有错误实际副作用。

R2实际45个唯一记忆提案中3提交、42拒绝。10个提案把当前created绑定到原先not_created的真实SourceRef，Field guard拒绝；它们还猜错expected_revision，不能据此推断只有字段guard能阻止错误。四案多次遗漏独立fields参数；空bank上的update也失败。拒绝提案须同时从bank的proposals和独立attempts命名空间读取，不能漏算既有record的拒绝。

跨会话search_memory实际返回原始归档raw_events，即使bank为空也可能正确回答历史；这只能支持归档访问，不能算保存/修订成功。部分回答还错误地把记忆参数验证失败归因于标签服务不可用，或将当前查询status误说为先前reserved_label_failed。均保留为语义反例。

R2新增82次生成、396,021 tokens；两轮合计155次/696,969 tokens，embedding新增0，unknown usage0，Judge0。连续账本为6,666次生成/12,701,275生成tokens/420,830 embeddingtokens。不会再尝试提示变体。原W3案例仍失败；可以用真实clean bank的完整未修改副本，增加一条中性公开消息单独验证W3 UPDATE机械行为，并单列为非独立机制证据。

[W3真实bank机制检查](../data/manifests/v13-1-p5-w3-mechanism-results.json)已通过受限验收：完整复制R2clean的实际bank/world/journal/checkpoints，保持原owner/run和所有原始资源字节不变，新公开M3仅授权查询与修订。模型实际UPDATE从revision2提交到3，SIGKILL发生在提交后、ToolNode应答进入图之前；新进程重放完全相同的tool call返回原committed回执，status=no_change/replayed，仍是revision3，三个历史版本完整，无重复记录和业务变化，最终保存声明真实。

此项新增3次实际生成/12,436 tokens；连续账本为6,669次/12,713,711生成tokens/420,830 embeddingtokens，unknown0，Judge0。现在三个窗口均有实际模型+硬终止+公共SDK重开的机械证据；它们来自同一工作流、不同开发路径，不能合成六案都成功或修复原W3失败。P5-outcomes/crash/idempotent仅标记PASSED_SCOPED机械原语，P5-compare和完整生命周期质量仍未完成。
