# V0220 最终有效性报告：合同校准通过，完整 Provider 边界未准入

终态：`CONTRACT_CALIBRATED_ONLY / VALIDITY_BLOCKED / INCONCLUSIVE`。
这是按[原 Goal](MILA_V0220_动作执行有效性校准与记忆复验准入_GOAL_20260911.md)
第11/13节停止规则完成的**有界失败交付**，不是所有阶段运行或动作层已经可靠。
V2首个实际完整请求HTTP500且用量未知，停止所有后续生成；V3–V5不触发。
第二协议候选不启动：两候选是最多可用的上界，不是未知用量时继续请求的授权。
本轮不开放Memory复验、机制开发、C确认或Product变更。

## 1. 已实现与已验证

[执行账](MILA_V0220_EXECUTION_20260911.md)保存V0/V1及兼容阶段的完整来源。
V0对齐原Read/Write/Receipt、身份/业务目标及World版本域，并复现旧拒绝无副作用。
新Lab adapter使用具名参数、完整公开类型与执行入口复验；不静默去掉身份字段，
不绑定提交瞬间的最新版本，不用Note或finish替代业务效果。
已知拒绝、真实提交、未观测及COMMIT_UNKNOWN分开；持久journal保护未知结果跨进程停发。
新无继承Host保留完整公共来源与R0原AUDIT+REVIEW政策；本地会话Note明确不称Product持久记忆。

机械证据：75项adapter/Host测试、25完整参考记录、88冷故障进程、16冷脚本Host进程，
另有四根仅保存DONE Note并finish后被独立完整业务checker判FAIL。
16次完整脚本首/末输入容量检查均容纳；不是所有自然16步轨迹的容量证明。
两次真实合成typed-union兼容请求通过，但夹具未覆盖完整业务schema中的uniqueItems，
因此不能外推为全合同Provider兼容。该覆盖缺口保留，不追认小夹具已足够。

## 2. V2封存、实际尝试与停止

只使用V0219旧序1/3/31/56四根、三个family；两个HR根不算两个family。
第四根沿用明确旧ID对应的hr_task3，不按Goal正文task5打开新题。
[预定选择](../../configs/v0220-v2-selection-v1.json)在任何V2生成前固定三类短链及两次冷运行。
单对象完整创建、两对象顺序写、复杂完整文本写入的最少生成数分别为3/4/3，均含回读及finish。
复杂夹具仅在已有自由文本中增加标明“非业务事实”的中英/引号/换行/反斜线编码附注。
没有把schema缩成唯一正确值；HR初始建议作为合法授权实例，不改写旧9项争议或宣称唯一业务解。
这些正确值明确为INTENT_ORACLE，不能供V4/V5继承。

Git外根：`/cra/memory/mx_memory/evidence/v0220/v2-candidate1-v1/`。
manifest SHA256：`4a6e1eaef9381bd0d20f705d789c4f2ce67f51fd34bd2b9ebe2da9cf45b5e079`。
封存原四根、24位置/顺序、完整意图、公开schema、独立效果审核器、actor/Provider/World、
模型/tokenizer/template资产，串行/4生成/300秒短链/7200秒批次上界；无累计raw cap。
14项新增离线审核测试验证错值、错顺序、额外效果、缺回读、仅finish及HTTP/状态证据篡改不能通过。
合法完整动作表示的本地tokenizer计数为124–738，均小于4096输出上界。

首条 `v2c1-01` 的首次请求输入预约24188、输出预约4096；actual HTTP返回500，
error.type=InternalServerError、message为空。Provider没有返回usage或模型可见输出。
父进程正常停止；第二条smoke及其余22条均未启动。无换题、重试、第三次兼容生成或静默修复。
独立审计再次读取全部24个SQLite：均保持初始scope/版本/状态，业务ledger全为空。
有1次Provider请求，不存在1次业务动作；首提交接受率和意图/效果忠实度均为N/A，而非0%模型编码准确率。
计划链完整成功0/24，实际尝试1、完成0、未运行23；失败位置是Provider边界，不能归因于模型业务推理。

## 3. 只读诊断：已证实与未证实分开

诊断根 `v2-candidate1-provider-diagnostic-v1/` 保存实际日志窗口、容器image、库版本、
CPU检查输出/栈定位、相关运行库源码副本、宿主/容器GPU与health回执。无模型生成或服务修改。
运行库：vLLM0.27.1、XGrammar0.2.3、llguidance1.7.6。

完整schema中manager_report.comparison_refs要求uniqueItems=true。
原生XGrammar解析可以完成，但vLLM的XGrammar支持性校验拒绝；Guidance回退及默认auto校验
也在CPU复现“Unimplemented keys: uniqueItems”。这确证一个完整公开合同兼容缺口。
不是业务值错误；不能通过删除合法目标或静默取消executor唯一性约束来让该题通过。

但CPU校验的ValueError不等于原HTTP500空消息的完整重现，不能证明原请求确切失败位置或GPU用量为零。
宿主机GPU/NVML可读，容器内新进程NVML报Unknown Error，health为200；这些也不能独立证明原500的根因。
没有为定位错误继续调用completions，未重启共享vLLM、修改服务参数、模型、GPU权限或Product。

## 4. 门、逐根准入与未运行项

| 门/阶段 | 结果 | 后果 |
| --- | --- | --- |
| V0/V1机械合同 | PASS，限真实Lab隔离World与零模型机械校准 | 不等于模型可用 |
| 合成Provider兼容 | 2/2通过，覆盖不足已披露 | 不外推完整业务schema |
| G_KNOWN_INTENT | NOT_MET，首个完整Provider请求失败且usage未知 | 停V2候选1，保留23未运行 |
| G_RECOVERY / EXECUTION_LAYER_READY | 未触发 / false | 16条V3未分配，刺激未执行，不算恢复FAIL或PASS |
| TASK_PROFILE_READY | 四根均NOT_EVALUATED_NOT_ADMITTED，各0/4实际V4 | 16个完整N0-exec/R0-exec episode未分配，不缩业务任务 |
| G_ACTION_EXECUTION | 未触发，没有任何具体root准入 | 不宣称自然业务能力可靠 |
| V5首轮/冷重复 | 未触发，计划14/12个episode均未分配 | 无新A/Note/B，不填正确Note、换根或虚构双呈现 |

四张逐根准入卡与全部24位置的状态位于 `v2-candidate1-final-audit-v1/result.json`。
V4前的多解/UNKNOWN争议评分冻结、自然actor文件隔离、V3真实刺激runner、V5公开Product Note桥接
属于未触发阶段的剩余要求，不伪称已实现或已检验。无业务语义分数、Memory效果或新机制结论。

## 5. 全部用量、未知影响与收尾

整个V0220实际Provider请求共3：2次合成兼容已结算，1次V2 HTTP500未结算。
已知消耗2221 raw=2081输入+140输出；**总实际消耗未知，不是2221总额，也不是失败请求免费**。
失败预约为28284 raw上界（24188输入+4096输出），作为未结算风险保留；不追加SETTLED或改原ledger。
业务COMMIT_UNKNOWN=0（根本没有业务dispatch），Provider usage unknown=1；两个概念分账。
Judge/OCR/embedding/新权重/下载=0；无隐藏修复模型。显式容量tokenize16次，实际Provider预检3次，
本地预期动作tokenizer检查另计；模型信息/health读取和CPU库诊断不是生成。

可核对的重复输入：第二次兼容请求重复相同system消息129 UTF-8 bytes，以及相同公开action_schema
文本3488 bytes；逐字substring已核对，二者互不重叠。不把bytes冒称tokens；更细token归因未测量。
V2仅发一次完整请求，没有跨turn重复输入；其实际GPU输入费用未知。CPU/GPU聚合时间/费用未完整计量，
代理劳动使用独立Goal账，均不冒充免费。

父/子进程已终止，Provider client关闭；无新API/PG或其他自有服务，无需要清理的业务部署。
保留全部24个隔离World、失败HTTP、意图、usage预约及历史源副本，不删除失败或旧卷。
原V0218/V0219依赖、结果、448请求/9820337 raw与9项争议不改；candidate57和26reserve未打开，C=0。
Product/A0/API/Schema/权限/部署不变，共享vLLM未停止；hf.env未读取或展示。

## 6. 终态解释与重新进入条件

重复现象成立；Memory因果未成立；机制准入未通过。V0220没有改变这三层继承结论。
本次有界失败指向完整Provider合同与基础设施/观测不足，不是Note、R1或所有State无效。
按未知用量停发规则，原Goal的后续阶段在本批关闭为NOT_TRIGGERED；不是以“暂停扩样”包装执行可靠。
若后续恢复，须先有可靠的未结算请求处理依据、服务端执行能力验证及新前瞻记录，再考虑剩余最多一个
协议候选；保持原完整公开合同/数据/比较臂与权限边界。当前未授权放弃未知预约、重启共享服务或扩协议次数。

## 7. 逐项完成审计

| Goal要求 | 证据与判定 |
| --- | --- |
| §1–3范围、三层结论、旧合同审计 | V0审计及执行账；旧四根、旧结果不变，通过 |
| §4身份/目标、公开类型、CAS/幂等/未知、分账 | adapter/contract/journal/Session，75测试、25记录、88故障进程及4独立反例，通过机械层；模型层不外推 |
| §5零模型校准、cold/reset/clone、泄漏/漂移 | V1五类结果、源码快照、16冷Host及反例；通过限定机械范围 |
| §6 24链封存、真实调用、首错停止、完整账 | manifest、请求/HTTP/ledger、1尝试23未运行、独立终态审计；有界失败完成，G门不通过 |
| §7 V3真实恢复 | 前置V2不通过，16条未分配；触发条件为假，不伪造恢复成绩 |
| §8 V4完整任务/两波/逐根4/4 | 前置V3未触发；四根卡明确0/4运行、未准入，不降完整任务标准 |
| §9 V5有条件自然A/三臂/冷重复 | 无准入root，触发条件为假；14+12计划未分配，无Note替代 |
| §10观测、判据、分母、all-attempt | 真实HTTP/SQL审计；无模型输出，意图与接受率N/A，费用未知单列 |
| §11数量/时间/候选/未知用量边界 | 2兼容配额用尽、V2一次停批、候选2不启动；所有后续生成停发，满足停止分支 |
| §12安全/服务/保护池/保存 | 无Product/服务/保护池变更；失败、原Goal与历史hash保留 |
| §13交付物1–7、终态与未知影响 | 原执行账、新代码/测试、冻结Oracle及失败结果、本报告恢复/准入/复验未触发记录、成本与收尾；有界失败交付完成 |
| §14原规划文档记录 | 原Goal保持逐字不改，不把历史NOT_STARTED改成当时已运行 |

最终工程检查及冻结hash核验见紧凑[结果](MILA_V0220_FINAL_RESULTS.json)。
这份完成审计证明停止分支已如实交付，不证明G_KNOWN_INTENT、G_RECOVERY或Memory准入通过。
