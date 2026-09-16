# MILA-V02-05：评价来源绑定与续做时间修复

状态：`ENGINEERING_VERIFIED / MODEL_EXECUTION_CLOSED / EFFECT_NOT_EVALUATED`。
本轮修复SIM02启动前两个实际缺口：评价就绪原先只检查配置字符串；A/B续做只发送问题，
遗漏来源包的`question_date`。没有启动新模型、Provider tokenize、Product服务或公开压测。

## 实现与证据边界

`tools/run_v02_e2e_generality.py`在prepare启动服务前校验评价文件与完整来源文件的SHA256，
以及问题、时间、首次实际使用边界、必要条件和来源引用。每个引用必须唯一定位到session/turn，
role与字符范围匹配，精确UTF-8 span摘要一致。prepare保存原始文件字节；run在授权检查之后、
G启动之前重新校验冻结文件。来源或评价文件变化不能仅靠保留`SOURCE_ASSERTIONS_FROZEN`
字符串继续运行。校验证明引用身份一致，不自动证明断言语义正确或评价完整。

续做保留原问题文字，统一追加原始问题时间，A/B收到同一任务；缺少时间在G启动前停止。
记录续做任务SHA256，完整实际Provider输入仍由现有Host记录。G继续收到原先正常档案整理任务，
不传入续做问题、时间或答案。评价文件位于各Host工作区之外，不加入来源快照、恢复记忆或
任务提示。实际Host请求路径的MockTransport测试验证A/B时间均进入请求、评价canary未进入请求；
这些是网络替身下的工程证据，不是新模型会话。未更改正常文件、来源首尾、检索能力或记忆策略。

## 已打开开发材料的评价依据

沿用既定材料0a995998，44 sessions / 484 events，没有重新挑题或读取gold标签文件。
[来源评价约定](../../data/fixtures/v02-e2e-evaluation/0a995998-source-assertions.json)
记录5条断言、7个完整原始用户turn引用、首次实际使用边界及未评价项。
原问题时间为`2023/02/15 (Wed) 23:50`。

来源推导的预期是2项：待取的西装外套、换码后待取的一双靴子。重复提及同一靴子不重复计数，
计划去取不当作完成，向姐姐借还衣物及洗衣不计商店事项。约定显式列出“一双算一项”、
“包含干洗取衣”及“未报告完成不证明现实未完成”的解释范围。
这是一份可审查的开发判据，不是独立gold认证、模型答题结果或留出泛化证据。
固定引用不能单独证明全档案没有遗漏；后续语义判定仍须按来源与预先边界核验。
没有自动语义评分器或新增Judge；无法可靠判定仍记未评价，不默认PASS。

来源SHA256：`9a9186bca9af27696878c06b3d65ec4f846fad7429e9e8aa5167a7d0c8def5ee`。
评价SHA256：`c934ce09eeaccff869c51f2a803fb22fadc9a8272ef3a79ab303a80a96cdf4df`。
续做任务SHA256：`fc823b61dfbc0b667090182feb5421fdffa706d2e85543492cc44a8c4dffb113`。
SIM02配置仅增加评价文件引用并标记来源断言冻结，transport仍false，新增模型分配/token仍0。

## 检查及失败保留

新增20项测试覆盖身份/位置/时间错误、启动服务前拒绝、原字节保留、零授权、运行前重查及
无时间不启动G；既有编排和实际Host请求替身测试补充时间一致性与评价隔离。
全Lab `uv run pytest -q`：**357 passed，2.73s**。boundary、Ruff `src tests tools`、
mypy `src/milai_lab`（30源码文件）、build通过。Product运行源码不变，本轮不重跑真实PG回归；
上一增量1164项真实PG测试仅作为历史证据保留。

首轮定向检查28通过、1失败：新增断言误要求任务独占一条消息，而实际消息还附恢复入口。
改为验证user消息以完整任务及时间开头，没有缩短任务或删除恢复入口。另修正测试中的未用变量
及超长行。首次实际零授权离线探测正确被阻止，但诊断脚本误期望短错误名；核对现有完整错误
`NO_NEW_MODEL_AUTHORIZATION_HISTORICAL_BATCH_CLOSED`后修正诊断预期，未改授权门槛。
上述失败与最终检查记在忽略目录
`artifacts/v02-e2e-generality/evaluation-preflight-20260907a/`。

实际候选配置离线验证：全部7引用身份一致；仅有config、尚无来源/服务目录的run调用即被
零授权门阻止。Product pin再次核验为
`56a0dab6df6dedd4540d3cc5a59fc1f9013505275e91cb7050b3d8eb56482e0c`，锁摘要
`7739ecb40e63d5556ee5c90547603f6fcc05eca96da89e593cfb6aef0aa57322`，未改历史pin。

## 未完成范围

D0本轮只补齐SIM02的来源绑定与时间边界，不代表所有任务评价已冻结。原生Host恢复及成本
观测仍需各自的真实证据，轻宿主结果不能外推。完整P1/P2/P4及D0–D3仍是部分完成；
公开服务300ms门槛、混合负载退化及租户公平性缺口未消除。D4/D5未进入，SIM02未生成。
下一步仍按这些实际缺口推进；本评价约定不产生新模型额度，也不证明分层记忆已有增量价值。
Schema保持`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
