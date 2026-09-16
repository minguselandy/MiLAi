# V0220 执行账：动作合同审计与执行层校准

状态：BOUNDED_VALIDITY_FAILURE_DELIVERED / V1_MECHANICALLY_CALIBRATED / V2_STOPPED / V3–V5_NOT_TRIGGERED。
用户明确要求执行[原Goal](MILA_V0220_动作执行有效性校准与记忆复验准入_GOAL_20260911.md)；
原文“仅规划”保留为历史，不修改冻结原文。V0/V1已执行；两次独立合成兼容生成已结算。
V2封存24条后首个请求HTTP500、usage未知而停批。最终结论及逐项完成审计见
[最终有效性报告](MILA_V0220_FINAL_REPORT_20260911.md)与[紧凑结果](MILA_V0220_FINAL_RESULTS.json)。
功能与实验有效性优先，累计raw cap=null；后续阶段仍逐批封存、按门解锁，不提前预约全部模型请求。

## 已核对的范围及原始证据

[执行计划](../../configs/v0220-execution-plan-v1.json)固定V0219原四根及原次序1/3/31/56，4roots/3families。
发现Goal正文的“人事task5”与冻结记录不一致：第56根 `A-4d36e6825968f3ce3862` 实际为 `hr_task3`。
按更明确的“只用原四根、不打开新题”要求沿用该root，不改成另一个task5。另一人事根为 `hr_task4`。
candidate57及26reserve未打开；不扩benchmark、重跑旧波、重开C2或开发Memory机制。

Git外 `v0220/v0-contract-audit-v1/result.json`：
SHA256 `5864a2dbfa9acd0d9bcf878e9f8a4f31419fed9944a0e6cda87c6230f95a9447`。
原Goal字节、旧schema/tools、四根公开read schema、已运行代码及依赖hash和四个隔离SQLite拒绝复现留存。
旧全波296次拒绝，B阶段274次，其中身份字段156次；不改变V0219原判断或费用。
审计脚本后续仅格式修订，原执行字节另存 `executed-audit.py`，原result/script hash保持可核对。

## 新实现：只在 Lab 新模块中

| 模块 | 当前实际职责 |
| --- | --- |
| [公开合同](../../tools/v0220_action_contract.py) | 从公开record_schemas生成read/write模型、具名arguments和逐action/target schema；完整字段/type/enum约束，不用私有postcondition选择答案；二次字符串编码取消 |
| [执行adapter](../../tools/v0220_action_adapter.py) | dispatch入口再次验证，不静默剥除身份；沿用原World级CAS；结构化拒绝、durable operation查询、真实effect/hash回执；业务错误但结构合法的值仍可提交供独立评分 |
| [dispatch journal](../../tools/v0220_dispatch_journal.py) | 新的Lab本地SQLite调度元数据，不是Product Schema。逻辑动作派发前持久记录；同ID不同payload拒绝；未知结果跨重启阻止新逻辑写入和clone，允许完全相同请求重放/真实已提交回执确认 |
| [零模型审计](../../tools/audit_v0220_contract.py) / [完整记录校准](../../tools/calibrate_v0220.py) | 旧证据、全部公开字段和已有参考夹具的实际本地效果校准，原始数据留Git外，不算自然模型能力或V2 Intent Oracle成绩 |

公开operation查询本身只读。可信Host确认实际已提交回执时，只更新dispatch投递确认元数据，
不改业务记录/ledger；查询未见operation仍为committed=null，不推断未提交、不释放未知停发。
已知CAS拒绝后的新请求必须使用新的逻辑operation ID；未知传输重试复用原ID和原完整请求。
保存Note/finish不进入business执行器；完整任务判据不作为Host工具。
新[无继承Host](../../tools/v0220_session.py)已接线：会话内Note为显式LOCAL_SESSION_ONLY，
使用独立SESSION回执域，不称Product持久记忆；N0-exec/R0-exec均有相同可选保存能力。
R0逐字保留原BASE_SYSTEM + AUDIT + REVIEW；完整六资源预读，两臂无旧Note/Oracle输入。
V5公开Product Note接线仍未实施，不用本地会话笔记代替跨进程公开恢复。
旧Host/World/Provider/checker未原地修改，没有启动无关Product服务或调用私有Product状态。

## 已完成的零模型证据及边界

[52项adapter测试](../../tests/unit/test_v0220_action_adapter.py)通过，含：完整创建/替换与跨对象World版本、
中英文/转义/嵌套/null、身份/跨scope/未知字段/非有限值/重复JSON键、陈旧版本、
同operation重放和不同payload冲突、丢回执前后两种故障、未知状态跨adapter重启停发、
真实子进程回读、clone隔离、合同漂移、澄清不取消原记录、结构合法但语义错误不被工具代解。
这些是脚本与合成场景，不是模型首提交率、自然业务通过率或Memory效果。

Git外 `v0220/v1-complete-record-smoke-v1/result.json`：
SHA256 `474c02c2d150014b712747b0938ec3ab15fcd81ae236a05befc5813040740000`。
原四根全部25份参考记录首次合法提交，25次同请求幂等重放、25次存储对象payload无副作用拒绝；
实际ledger恰25个业务效果、公开回读逐对象一致，最终记录集等于参考集。
每根独立SQLite/scope，保存完整schema、动作/回执/readback/世界和执行代码副本。
夹具转换明确在evaluator中移除存储object_id，**不是运行时修复模型payload**；
只验证公开结构/执行等价性，不改变原9项语义争议，不证明参考方案是唯一正确业务解。

## V1完整故障矩阵、Host接线与兼容验证

上述25记录smoke保持原始历史证据。后续完成机器可读Read/Write/Receipt一致性验证，
已知拒绝可按operation查询；未观测提交仍committed=null，不与已知拒绝混同。
新增[23项Host测试](../../tests/unit/test_v0220_session.py)，与52项adapter测试合计75通过。
包含真实effects/readback、结构合法业务错误不代解、跨臂/作用域/配置/复制源码漂移、
私有字段与字符串canary、未知提交后下一次生成为0、重启停发、Note/finish分账与自然臂错误复发停发。
首次单测运行有1项夹具调用用了错误的publish位置参数；修正为既有keyword-only接口后通过，未调用模型。

所有以下文件位于Git外 `/cra/memory/mx_memory/evidence/v0220/`，执行代码副本/输入hash均已封存：

| 证据result.json | 实际范围及结论 | SHA256 |
| --- | --- | --- |
| v1-fault-matrix-v1 | 原四根，88冷进程；25完整记录首次效果、每根12非法输入、两类版本前提、提交前/后进程丢失、scope/config拒绝与clone隔离均通过 | 5476fd9681e1d72f6efacd40a481475ea65dd9044a54e2f5bf41cbe60773afe1 |
| v1-host-matrix-v1 | 四根×Oracle/R0接线×2冷进程=16，全部通过；Provider为脚本夹具，真实SQLite效果；不是V2/V4成绩 | 781c5af70eede5034dfe33735fde4c9068b824a9dcb1e7d95a1e34a3da0368d2 |
| v1-capacity-preflight-v1 | 16个完整首/末输入tokenize均容纳；最大54033+4096≤65536；未生成、不证明所有自然长轨迹可容纳 | df0d25b95b754e548e4ce47fc78ae823d0bb0df3c46e5a220c2e3a59d1139799 |
| v1-nonbusiness-checker-audit-v1 | 四根仅保存DONE Note并finish，实际World/ledger不变，独立完整业务checker均FAIL；私有checker不进入Host | 9db961b3b6dabef96358a1639f79eb59a7fe29776b753861bf912ce20e41e7bb |
| provider-compat-v1 | 真实本地模型2/2 typed union合成请求成功；未执行业务，不是Intent Oracle矩阵或自然任务成绩 | 62b6b92ee3562194e7971bf6efbd075fda2e3aa5de85c92bef0ab77703e234cf |

兼容manifest `69a01d0efe372bd2f2016a7838f4ad83de20e3cc35df60c49cabf2c45413b6c9`
在请求前固定两次上界、完整输入/schema、代码、模型/tokenizer/template资产与前置证据。
兼容消耗2请求/2221 raw（2081输入、140输出），pending/violations=0；Judge=0。
该两次兼容配额已用尽，不再隐含增加兼容生成。原Provider的实际HTTP/request/usage均保存。
本轮显式容量tokenize16次；兼容请求自身还各有1次Provider完整输入tokenize，分母不与生成混合。
所有Provider连接已关闭，无新API/PG或Product服务；共享vLLM未改变。

## V1结束时的准入边界（历史记录）

V1机械校准通过，只允许继续封存V2，不等于EXECUTION_LAYER_READY或Memory准入。
下一步封存V2的24条已知意图短链、完整动作值/来源审查、独立效果审核及真实模型冷进程runner，先两条smoke。
出现首个非预期协议错误即停该候选，不跑完整矩阵重复撞错；最多两个协议候选版本。
V3真实恢复、V4无旧Note完整业务准入、条件V5复验与最终报告均未运行，不能用当前测试/参考记录PASS替代。
V4须预先处理source-grounded多解/争议且隔离V2答案缓存；V5须具体root通过4/4与跨2family门。
以上为V1交接时的剩余任务；随后V2已按下节实际尝试并触发有界停止，不继续分配后续请求。

本增量最终全Lab回归：1459 passed / 1 optional Host SDK skip（44.37秒）；boundary、Ruff src/tests/tools、
mypy src/milai_lab（39文件）、sdist/wheel build、git diff --check通过。
实施后重新运行V0219冻结依赖验证，原69项依赖/manifest仍一致。
原接续回执 `v0220/progress-handoff-v1.json`保持历史；新状态为 `v0220/progress-handoff-v2.json`。
五组新增校准/兼容冻结清单、V0219原依赖和原Goal字节最终均再次核对一致。
该V1交接当时无未结算请求或新增服务；不适用于随后发生的V2未知用量。

## V2实际封存、失败与后续门关闭

`v2-candidate1-v1`在调用前冻结原四根×三种短链×两次冷进程，共24条，smoke为前两条。
manifest SHA256 `4a6e1eaef9381bd0d20f705d789c4f2ce67f51fd34bd2b9ebe2da9cf45b5e079`。
独立审核器14项离线反例通过；真实HTTP/usage/typed动作/receipt/SQLite与公开回读逐步连接。
首条第一次请求HTTP500，没有模型输出、业务dispatch或Note；23条未运行。
28,284 raw预约未结算，原Provider ledger保留；不因没有输出而记免费，不再发请求。

真实运行库CPU诊断发现完整公开schema的uniqueItems不被vLLM XGrammar/Guidance校验支持。
这未覆盖在先前两次小型兼容夹具内。原空消息HTTP500具体位置仍未知，不能用CPU ValueError追认零usage。
宿主NVML可读、容器内新进程NVML异常，health200不证明可生成；无共享服务重启或配置修改。
四根全部24World经独立审计仍为初始状态/空ledger；首提交接受率为N/A（业务动作分母0）。
G_KNOWN_INTENT未满足；V3/V4/V5均未触发，四根自然任务均未准入，第二协议候选因未知用量停发而不启动。

本Goal实际Provider请求3，其中2次兼容2221 raw已结算、1次V2用量未知；总实际raw未知。
最终结果及停止原因见上链报告，所有失败、未运行项、争议、保护池与成本保持独立。
