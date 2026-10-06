# MiLAi-Edit 当前实验检查点

快照：2026-10-06 14:36:53 Asia/Shanghai。**旧正文交付与来源重述已有真实证据；条件化局部编辑尚未显示稳定优势。
冻结7cc的传输续行已完成66次，最终生命周期问答仍不完整。没有最终候选或新候选前缀，Product NO_GO。**

保留I2、B0/B1/B2/M和现有Qwen3.6家族。实验源码固定`7cc1363977a5ebc74ea1d43064d40fe7a329e1b5`，本轮配置
`milai-edit-post-b0-common-source-reader-transport300-v2`。报告提交与实验源码分开；本次只更新七个Lab报告/状态文件，
新增模型调用0。本地三文件`from_unit`修复草稿未纳入提交、未进入任何模型队列。
PR85保持open、draft、未合并，基础仍是PR84开发分支；本次报告回滚参考`4bfa41e`。

## 当前真实进度

| 范围／冻结版本 | 实际完成或尝试量 | 结论及限制 |
| --- | --- | --- |
| 早期4357d46 I1/I2前缀 | 每接口每组四用户前八会话 | 选择I2；不替代新候选前缀 |
| 旧4357d46完整历史 | B0 277/277；B1 115/277；B2/M各0/277 | 剩余延后，未取消、未补零；四组完整比较未完成 |
| 497非思考，output8192 | 80次／162,068 known，80 stop | 条件形成、普通更正保持；范围/共同条件/撤销失败 |
| 同497原生思考，output32768 | 80次／384,395 known，80 stop | M共同分支实际图结构例外生命周期有限正例；原分支失败，最终Reader均不完整 |
| 7cc实际旧状态Reader诊断 | 9次／22,080 known，9 stop | 8最终回答不完整；中间控制错误日期、无依据附加推测 |
| 7cc原分支，timeout180 | 30尝试／29响应／131,913 known | B2第30次Writer超时，确认未提交记忆；实际生成用量未知 |
| 7cc原分支未尝试续行，timeout300 | 14次／70,261 known，14 stop | B2从实际revision3备份继续，M自空库；M未使用例外覆盖算子，最终Reader仍不完整 |
| 7cc共同条件分支，timeout300 | 36次／190,616 known，36 stop | M保留一般规则并更正共同条件，但未使用例外覆盖关系；四组最终Reader均不完整 |
| 7cc助手准确重述控制，timeout300 | 16次／50,213 known，16 stop | 四组状态/版本/支持均不变，8回答正确保留用户收入陈述与归属；有限构造正例 |
| 7cc用户确认／助手无依据强化控制 | 0/20、0/16 | 已声明，尚未启动、未取消 |

原141声明现有105尝试、104响应、465,083 known token，36次未尝试。102次传输续行声明已完成
66次，不是额外102个任务。timeout180与300结果分开报告，跨配置只累计成本，不拼方法成绩。
更早233思考80次含9次length、8ed来源控制132次及所有首次失败保留。
v1 M因Reader断开已FAILED收口：129/277维护、128/277完整评估，149评估不完整，已非活动队列。

## 最新语义结果

**原分支续行：**M形成频率内容和两个限定，普通`change_value`保留未重述限定及旧支持；
夜班四次被保存为独立content-only记录，没有override或共享条件关系。撤销使用`retract`
删除该夜班单元，一般三次及原限定仍在。这支持有限的内容保持，不能归因为`add_exception`／
`remove_exception`机制。无新事实返回合法`no_change`，重申返回空提案；实际状态、版本、支持不变。
最终Reader仍拒绝把一般三次用于两个班次。B2后续重申修复一般三次及限定，不抵消先前损坏。

**共同条件分支：**B0在更正共同条件时丢一般频率；B1先丢未重述限定，增加范围后再丢一般频率。
B2真实形成条件关系，但普通频率更正的新值/保留限定正确，变化节点只用当前e后，旧绑定h无法
确定原节点对应关系，遭`EDIT_RELATION_SUPPORT_BINDING_INVALID`。这是具体合同局限；另两次
范围/共同条件提案也有语义遗漏，不能全部称为正确更新误拒。拒绝后保留初始频率不算成功保持。

M使用`append`增加夜班/日班内容，用`change_condition`更新节假日、`change_value`更新开始时间，
再以`retract`撤销夜班单元，一般三次和新共同条件仍在；没有实际override、`add_exception`或
`remove_exception`。最终四组回答均不完整；M另把2030-03-04的“下周一”算成03-10，正确为03-11。
旧497共同分支实际图结构生命周期正例仍保留，不能移作这轮7cc机制证据。

**来源准确重述：**四组均保留原始用户18,000 USD陈述、user角色、2030-04-01及原支持；助手
复述后没有新版本。8条回答正确指出金额和原陈述者。这里只检验准确复述，尚未检验助手冲突
补充或后续用户确认；正确最终确认也不能抵消中间错误归属。

Root复核本轮36事件、31回答及66对HTTP/usage。26个HTTP实际交付44段旧支持正文、550 token
occurrences，正文/角色/时间、选中支持、共同正文预算与完整请求容量一致。27提交、3拒绝、
4 no_change及4空envelope是操作计数，不是语义成绩。交付发生不证明证据蕴含。

## 草稿、CI与成本

本地正在验证全量重写的`from_unit`对应关系：把旧单元身份与旧事实支持分开，变化内容仍需要
实际新证据；不补遗漏、不把身份当作证据。该三文件源码/测试草稿尚未提交，相关SDK/Host、
静态/default-off检查、自身CI及真实模型复核未完成。本次模型全部使用冻结7cc，不使用此草稿。

既有7cc Root 412+52=464项工程检查、Ruff、strict mypy与边界通过，是此前源码验证；本次文档
发布不重跑源码测试。7cc自身Fast/Full成功；上一声明4bfa自身Fast/Full本次查询均success。
本次新报告CI按新提交单独核对。Product Schema/API/权限/Canonical、Archive及workflow未改。

本轮66次：141,050 input + 170,040 completion = 311,090 known，reasoning已包含在completion。
账本36,405→36,471请求，139,557,605→139,868,695 known，139,669,320→139,980,410 charged。
generation unknown保持3，embedding964,645/unknown0不变。原B2超时实际tokens=null，保守收费
60,013保留；只读SQLite已确认未提交，原未知Writer不重发。原始终态、配置及预声明actual0不改。
三批进程已退出，账本匹配、串行锁可获取，当前无模型队列；原始HTTP/DB/reasoning/日志继续ignored。
Post-B0各版本累计621尝试、1,804,956 known，只用于成本，不形成同版方法分数。

## 剩余范围

先完成已声明用户确认20次与无依据强化16次，逐批复核；验证具体重写对应关系修复和Reader实际
一般规则/撤销来源输入、日期计算。减少无效选择，不增加警告或审核平台。可用共同配置确定后，
按原计划从各自空库做四开发用户前八会话及事前固定第一用户完整历史，再完成同版四组比较。
同M低层/语义入口消融、一次固定较紧预算、原生机制/漂移、16保留用户、LongMemEval及外部基线、
Host功能和恢复、完整R0–R5/E0–E5及六项交付仍未完成。Root复核与同家族Judge不是独立确认。

[本轮66次结果](../data/manifests/milai-edit-post-b0-transport300-results-20261006.json) ·
[102次原声明](../data/manifests/milai-edit-post-b0-transport300-continuation-development-20261006.json) ·
[原30次失败](../data/manifests/milai-edit-post-b0-common-source-reader-original-results-20261006.json) ·
[当前状态](../data/manifests/milai-edit-v2-current-status-20261006.json) ·
[完整进度](MILAI_EDIT_V2_PROGRESS_20261005.md) · [复现](MILAI_EDIT_REPRODUCTION.md)。
