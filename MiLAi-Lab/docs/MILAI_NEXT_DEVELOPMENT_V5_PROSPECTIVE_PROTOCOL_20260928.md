# v5 V4/V5 前瞻小样本协议 R1

状态：INPUTS_FIXED_PREPARED_NOT_RUN。10个正式零模型prepare已完成，159项源码、27条公开消息，账本未变；
[prepare清单](../data/manifests/next-development-v5-prospective-prepare-20260928.json)绑定源/输入身份。V0–V3已完成，见[离线分析](MILAI_NEXT_DEVELOPMENT_V5_OFFLINE_ANALYSIS_20260928.md)。
先验证唯一现有方法：v4 R2 B0，语义方法提交 `24ef49945cd12eccbd85792fee3c256bf3fe6d2a`。
新增离线analysis模块不被runtime导入；原161项source/runner/package/lock字节一致。
实际执行的发布提交、159项prepare源码身份、输入/工具/参数/scorer/隔离/账本起点在真实调用前一并冻结。

## 输入、范围与可見要求

10个新合成脚本、27条公开消息，每脚本2–4个不同session；H在两个session之间回访旧session。
用户均为合成rowan，各脚本有独立run/namespace/Store/checkpoint/业务SQLite。
本批内容在v4方法冻结后新建，未参与v3/v4模型调试；任务族与旧诊断相关，不称原生benchmark、独立用户holdout或统计泛化。

| 顺序/脚本 | 会话消息 | 当前必须验证的内容 |
| --- | ---: | --- |
| A complete_plan | 2 | 明确保存五字段；新session明确逐项询问item/quantity/destination/packing/booking |
| B partial_plan | 2 | 保存完整记录；后问只评分quantity/packing，另三字段为diagnostic |
| C one_reply_format | 2 | 一次性LOCAL:及一句解释；后问checklist不延续格式、不保存 |
| D independent_update | 3 | 两个独立事项；只更新时间，保持日期/地点和钥匙事项；后来逐项使用 |
| E quoted_rule | 2 | 第三方green ink指令只作引用；明确不写，后来没有自采纳偏好 |
| F read_only_note | 3 | 真实形成后连续两次只读；字段回答及原记录保持，零mutating tool attempt |
| G explicit_delete | 3 | 两条明确独立可删除事项；实际DELETE纺织note，陶瓷note身份/正文保持；后来只见存活项 |
| H assistant_conflict | 3 | S1保存并真实回答6；S2更新9；回S1保留旧assistant6，当前Memory9，回答9 |
| I dynamic_world | 4 | 旧计划not booked；真实reserve/label一次且不改计划；新session实际lookup当前状态；再问旧snapshot |
| J moderate_bank | 3 | 真实创建六个明确独立单项note；两轮分别询问三个位置；全部仍可放入all预算 |

[输入与固定顺序](../data/diagnostics/next-development-v5-prospective-r1/execution-order.json)、
[四层义务合同](../data/diagnostics/next-development-v5-prospective-r1/obligations.json)、
[离线评分说明](../data/diagnostics/next-development-v5-prospective-r1/rubric-guide.json)同时冻结。
配置与[v4 R2 config](../data/diagnostics/next-development-v4-b-regression-r2/config.json)逐字节相同：
Retained、strict、memory boundaries on、N32/B6000/query10、Attention off、correction0。
不增加多臂矩阵、不把V3的空白精简候选部署进首轮。

133个分项：current41、persistent59、later30、diagnostic3。explicit合并current/later按复合ID去重，共71个。
Root在运行前逐项复核用户可见原文和持久意图；首草稿遗漏的三条显式确认要求已补入，未看任何新模型答案。
每个依据来自目标或更早已可见消息。诊断字段不能造成任务失败；不能要求未点名的附加答案、固定措辞或虚构标准ID。
精确item key用于业务调用来自用户公开提供的完整引用，实际reservation UUID由真实工具产生，不预设gold ID。

## 操作、生命周期和历史

预计8个形成请求事件，含15个逻辑事项；2个同事项更新请求、1个明确删除请求，合计11个要求持久变化的事件。
这些事件计数与59个字段/范围义务分别报告，不把一次写入的多个字段当多次形成调用。
G/J的独立记录要求有明确用户依据；其他脚本不按额外固定card count评分。
只读禁止实际mutation和mutating tool attempt，合法read/search可用并计费。

H旧assistant内容必须来自S1真实生成，并在回访HTTP中保留。新Store值9也必须实际交付；若前段未激活，不把后答正确当冲突通过。
I通过Host已有工具真实改变业务World，初始label服务可用；没有operator_memory或world_events注入。
S2明确禁止持久修改，因此not booked保留为旧规划snapshot；S3必须实际get_reservation，不能靠旧note或虚构状态。
旧session原transcript保留；S3是新session，不偷偷加入跨session历史。S4只问旧规划，不能误把live结果回填为记忆事实。
J六条必须真实形成，不能用预填bank冒充；记录完整送达和真实容量另验，不强制Attention。

## 门槛、运行与失败处置

核心gate按计划：explicit至少95%（本分母至少68/71）；所有requested持久变化正确；零误持久化、假saved、重复业务动作和隐藏rubric-only task failure。
另报告显式内容义务与no-business义务，防止大量容易的无动作项遮盖字段错误；完整脚本率及每类失败保留。
计划§17/20的dynamic world/assistant conflict基础稳定要求也必须独立成立，不能仅用合并95%推断它们通过。
unknown/unfinished不能当pass。任何实际失败先分类首断点，再决定是否触发V6/V7；不得看结果后改失败条件。

Root按A→J串行执行，每脚本只一次，真实Host/embedding HTTP并发1。一个语义失败不改变其余冻结脚本或方法。
脚本内若中断保留当前状态、费用与未完成消息；基础设施故障先诊断，不能靠观察超时擅自重启或覆盖attempted目录。
模型参数仍temperature0/max_tokens4096/thinking=false/context65536，每公开消息12次，embedding为bge-m3/1024。
不调整服务parser/部署/参数，不调用Judge/controller/selector，不自动补gold答案或修改Store修分。

所有真实调用之前：源码和协议发布、10个正式零模型prepare、输入/源码/工具/参数/顺序/隔离/scorer/hash冻结、实际服务models只读核对、连续账本snapshot。
prepare仅做一次，发布后核对同一输出身份，不为Git再运行它。
唯一账本为原树 `artifacts/ser-v20/budget.json`，当前2,994 calls / 3,785,491 generation tokens / 21,237 embedding tokens，
SHA `e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668`；以freeze时实际值为准，不清零。

费用分generation input/output、embedding、Store逻辑读写/bytes、业务调用、控制/失败/纠正/重试、进程wall/CPU、HTTPwall和unknown。
形成/维护/使用按execution-order的逐消息stage互斥记账。I业务动作/查询为use；一个字段多次评分不重复记费。
身份/receipt/HTTP检查与Root语义验收分开，进程0退出不是语义成功。

V5后按实际Observed/Expected、因果链、首断点、至少两解释、候选、混杂、最小下一实验、Continue/Pivot/Stop及Reflection报告。
V6若修当前约束须旧暴露回归和至少两条新的当前约束；V7只修实证世界/权威问题；V8须真实选择瓶颈。
本批所有运行过的内容随后都是已暴露材料，不能在修方法后继续称unseen。V9完成全部要求审计，基础Memory稳定仍待真实证据。
