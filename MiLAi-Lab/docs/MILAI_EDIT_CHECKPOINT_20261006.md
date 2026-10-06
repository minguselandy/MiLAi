# MiLAi-Edit 当前实验检查点

快照：2026-10-06 13:44:49 Asia/Shanghai。**接口与条件表示已改善，M在旧497共同分支有一个有限Writer例外生命周期正例；
尚未验证稳定方法优势。最新7cc原分支在30次尝试后超时停止，语义范围/撤销/来源仍有失败。
没有最终候选或新版本前缀，Product NO_GO。**

保留I2、B0/B1/B2/M和现有Qwen3.6家族。实验源码固定`7cc1363977a5ebc74ea1d43064d40fe7a329e1b5`；
报告身份与实验身份分开。本次只更新七个Lab报告/状态文件，新增模型调用0，方法与配置未改。
PR85仍open、draft、未合并，基础为PR84开发分支。回滚参考上次报告`8c80445`。

## 当前真实进度

| 范围／冻结版本 | 实际完成或尝试量 | 结论及限制 |
| --- | --- | --- |
| 早期I1/I2前缀，4357d46阶段 | 每接口每组四用户前八会话 | 选择I2；不是最新7cc前缀 |
| 旧4357d46完整历史 | B0 277/277；B1 115/277；B2/M各0/277 | 剩余延后、未取消或补零；四组完整比较未完成 |
| 497b8d8非思考，output8192 | 80次／162,068 known，80 stop | 条件形成、普通更正保持；范围/共同条件/撤销失败 |
| 同497原生思考，temperature1、output32768 | 原44+共同36=80次／384,395 known，80 stop | M共同分支Writer有限正例；原分支失败，两分支四组最终Reader均不完整 |
| 新7cc实际旧状态Reader诊断 | 9次／22,080 known，9 stop，Writer0 | 8最终回答不完整，中间控制日期错误，完整控制不通过 |
| 新7cc各组自空库原分支 | **30/44尝试、29响应／131,913 known；新增未知生成1** | B0/B1各6事件，B2 4事件后Writer超时；M未开始 |
| 新7cc共同分支及来源控制 | 0/36及0/52 | 已声明，尚未启动、未取消 |

更早2335ea9思考80次含9次length、8ed7826非思考/来源控制132次及首失败原样保留。
v1 M已因Reader断开FAILED收口：129/277维护、128/277完整评估，149评估不完整；不是活动队列。

## 新原分支30：交付有真实证据，语义更新仍失败

Root复核16事件、13回答、29对HTTP/usage、全部30请求投影及17 Writer packet/schema/messages。
14个HTTP请求实际携带24段旧支持正文，284 token occurrences；来自选中记录的真实支持，
正文、角色、时间、共同正文预算和完整请求容量均匹配。**这证明必要旧正文确实交付，不能证明
模型正确选择支持，亦未证明特定h-only拆分/同义改写误拒已经解决。**普通SDK模型任务仍待运行。

| 方法 | 观察到的行为 |
| --- | --- |
| B0 | 普通更正保持未重述限定文字；增加夜班例外丢一般频率和限定，撤销不能恢复。后续重申补回部分内容，最终Reader仍不完整 |
| B1 | 普通更正保持文字但丢限定的直接原支持；增加例外后整体断言归到本次来源。撤销只选旧证据并删限定而被拒；重申保留旧夜班例外，最终Reader仍答旧值 |
| B2 | 初始条件与关系真实形成，普通更正保持；增加例外将旧一般规则绑定支持用于新夜班而拒绝，也遗漏一般频率。撤销例外未形成却将一般频率换成泛化取消描述 |
| M | 本分支尚未启动；不计失败、零分或机制结论 |

12 committed、2 rejected、1 no_change及1空envelope只是操作计数。两次拒绝的提案还有
内容/当前来源问题，不能描述为完整正确更新遭误拒。拒绝后状态不变、后续重申修复、
未形成的例外或只加支持都不能算首尝试成功。完整Reader状态检查均无额外记忆写入。

第30次为B2无新事实查询的Writer，180秒ReadTimeout、无响应/envelope/提案/回执。
Root只读查询实际SQLite：current逐项等于发送前状态、revision3、无该请求proposal。
**记忆提交已确认为未发生；生成结果及实际用量仍未知。**actual tokens=null，按现有账本
规则保留60,013 token保守收费，公式已独立核对，不能报成真实用量或零用量。进程退出，
服务停止生成，串行锁可获取；不重发该Writer，不解析或补拼截断结果。

## 旧正例、Reader失败及实际输入诊断

冻结497共同原生分支M实际add_exception保留一般规则和两个共享限定，两次change_condition
更新共享节点，remove_exception删除已形成夜班覆盖和专属条件，一般规则、新共同条件及
支持仍存在。这是经实际前后图复核的**一个有限Writer正例**；原分支M仍覆盖一般频率、
误撤有效节假日条件，不代表稳定优于其他方法。

新7cc Reader9使用旧497各组实际交付状态、原问题和日期，不注入正确旧卡。8个最终回答
仍不完整；中间控制虽答3/4及相对限定，却把2030-03-04的“下周一”写为03-10，实际为
03-11，还添加无依据后续变化/确认要求，不能报完整控制通过。旧Reader9结果原件未改。

离线检查旧497共同分支M发现：撤销后一般规则仍在，但渲染不再保留一般规则标签；
实际最新取消来源与retract操作保存在版本中，Reader却只收到content/scope/revision，
没有最新撤销观察。**这是真实输入差异，尚未验证修复的因果效果。**不把任意content当作
通用规则，不用更多警告代替输入修复；若补读历史，须沿用真实公开接口/共同预算，另说明
来源可用的系统协议，不悄悄并入纯语义方法成绩。Root复核及同家族Judge均不是独立确认。

## 工程、CI与成本

7cc只向Writer补交选中记录实际支持范围，当前+旧正文8192token，当前来源批次4096；
旧e和当前e分别记录，未选范围不称已读。SDK复用实际成功read_source页，不重绑public
turn/current boundary，不放宽h字面保持、origin、CAS或权限。共同Reader区分retained_state
与source_history；RawRAG/Rolling Summary/A-MEM共用Reader，原生更新机制未改。

既有Root工程检查412+52=464项、Ruff9文件、strict mypy5源码及依赖边界通过；owner148
包含其中，不重复累加旧SDK341。报告更新未重复源码测试，工程通过不能代替语义效果。
源码7cc自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37415897766)和
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37415897714)均success，Full21/21。
原分支首次HTTP前Fast已success、Full在运行；依计划7.2做有限日常验证，Full随后完成。
此前报告8c自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37417295798) success、
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37417295792) in_progress（13:40:25查询）；
本次报告自身CI推送后单列，不能借用源码或旧报告结果。

本阶段53,703 input+78,210 completion=131,913 known，reasoning包含在completion内仅计一次。
账本36,375→36,405请求，139,425,692→139,557,605 known，139,477,394→139,669,320 charged；
新增charged191,926=known131,913+unknown保守收费60,013，generation unknown2→3，embedding
964,645/unknown0不变。7cc总计39尝试/38响应、153,993 known；Post-B0各版本累计555次
尝试／1,493,866 known，仅用于成本，不拼跨版本方法分数。当前没有模型队列。

## 剩余范围与下一步

141次声明尚有102次未尝试：原分支14（B2未尝试Reader/下一事件及M自空库）、共同36、
来源控制16/20/16共52。保留原180秒失败；拟为仅剩未尝试请求另声明300秒共同传输配置，
不改方法/生成/Reader/评分，不重发未知请求；**此配置尚未发布或启动**。B2延续须来自
实际状态的只读备份，M与后续分支各自空库，不注入手工正确旧卡，旧/新传输结果分开。

复核有限历史后依既有计划做最新候选四开发用户前八会话及事前固定第一用户完整历史，
再完成同版四组完整比较。同M低层/语义入口、一次固定较紧预算、原生机制/漂移、16保留
用户、LongMemEval与RawRAG/Rolling/A-MEM、Host功能及恢复仍未完成，完整R0–R5/E0–E5和
六项交付及旧延后范围继续。只用现有Qwen3.6，不重新引入第二家族部署要求。

本次JSON/计数/成本/账本、相对链接、仓库边界及diff检查单列在当前状态。raw/gold/HTTP/
reasoning/数据库/日志继续ignored；本次无源码、测试、运行配置、Product Schema/API/
权限/Canonical、Archive或workflow改动，PR保持draft未合并。

[原分支30次结果](../data/manifests/milai-edit-post-b0-common-source-reader-original-results-20261006.json) ·
[Reader9原结果](../data/manifests/milai-edit-post-b0-common-source-reader-results-20261006.json) ·
[141次原预声明](../data/manifests/milai-edit-post-b0-common-source-reader-development-20261006.json) ·
[原生80次结果](../data/manifests/milai-edit-post-b0-native-capacity-results-20261006.json) ·
[当前状态](../data/manifests/milai-edit-v2-current-status-20261006.json) ·
[完整进度](MILAI_EDIT_V2_PROGRESS_20261005.md) · [复现](MILAI_EDIT_REPRODUCTION.md)。
