# 正常端到端完成优先：SIM03失败与SIM04参数对象候选

用户已暂停OAuth，并明确要求不再以严格额度阻止正常端到端跑通。
本地新链采用每会话100万累计raw tokens、600秒、64请求、单请求输出4096的异常护栏；
每条G/A/B链最多3会话、总300万。沿用相同44会话/484事件的完整来源、预先冻结的续做题目及
来源断言，普通文件和公开Memory接口保持可用。紧预算成本验证推后，真实消耗仍完整累计。
旧批次关闭不改写；开发失败修复使用独立新目录，不自动重发未知请求，也不追加评测模型。

## SIM03终态

`artifacts/v02-e2e-generality/sim03-completion-first-20260907a`：G失败，A/B未分配。
G12次生成、input252,035/output4,818，共256,853 raw tokens；在线167.368966秒。
准备41.127187秒，含准备/执行/清理209.806534秒。没有UNKNOWN或usage超额。

前11个动作取得44个会话的首页；有MORE/next的页面并非完整会话内容，不能称通读全历史。
第12次尝试生成write_file动作，Provider返回`finish_reason=length`，4096输出token计入成本。
实际正文8323字符，其中2527个制表符；外层JSON未完成，已输出的arguments_json字符串内部
含未转义控制字符，JSON解析在位置84失败。没有执行或修补该片段，没有生成details/handoff。
这次失败位于Host动作编码/模型输出，非累计预算、超时或公开保存接口失败。
当时没有取得保存—冷恢复证据，不给语义续做或泛化PASS。

自有API/worker/G退出，PG停止且未OOM；原始产物、Provider回执及终态清理均保留。

## 已实现的通用修复

1. Provider增加独立的budget-preflights记录：在tokenize前记录尝试，之后记录实际计数或
   无计数的失败。预算拒绝不再丢失计数；预算接受仍不等于生成发送。生成账本继续独立确认。
2. 可选Host预算消息只包含机械额度，附在本次实际请求中，不在历史里累积；自身正常计费。
   提示明确下一请求再次支付全量历史成本，不强制总结、不删除内容、不扩大语义权限。
3. 可选`ARGUMENT_OBJECT`动作协议直接使用JSON参数对象，取消模型承担第二层JSON字符串
   编码。适配器仅为既有dispatch转换内部形状；原始模型输出保留，拒绝字符串冒充对象和
   不完整输出。工具白名单、scope、逐次资格检查、文件权限及保存合同保持原样。

第三项针对本轮具体动作编码失败，不声称仅凭工程检查已证明模型能够完成任务。
内层业务payload保持开放，不强制Memory item化，也不引入Hint或第二个语义模型。

Lab `uv run pytest -q`：381通过（3.03秒）；boundary、Ruff、mypy及build通过。
覆盖原生参数中的多行/引号/反斜线/中文/嵌套自由payload、拒绝伪对象与截断JSON，
并在旧/新协议下验证实际Host路径的来源撤销、跨scope及元数据失败均先于下次模型发送阻断。
测试使用模拟transport，没有额外真实生成/tokenize。

## SIM04执行边界

候选配置：`configs/v02-local-sim04-argument-object.json`；运行目录：
`artifacts/v02-e2e-generality/sim04-argument-object-20260907a`。
该批新导入三份独立、逐条公开核验的完整来源，准备36.325800秒；相同题目/评价只在G结束后
进入A/B。实际首请求已确认使用`tool / arguments / answer`协议，预算消息仅一份。
Product pin为`dca9f0b29ce1ba627ecd7de1a0be16abcd2096466cd326ed0d247574410a4c84`；
变化来自前述MCP OAuth Host/Origin修复，Runtime源码未在本轮修改。

SIM04原批次G正常完成：14请求，input333,335/output4,249，337,584 raw tokens；在线
196.665604秒。生成details.md（8064字节）和handoff.md（3083字节），44份完整来源不变。
保存携带484个真实Evidence引用，触及API/数据库256条上限，未启动A/B。
原始checkpoint保留UNKNOWN：公开MCP错误丢失结构化拒绝码，不能以GET为空替代操作确认。

### 原产物复用及容量修复

Product ADR-046与迁移0055将API和数据库引用容量统一为1024，仍保留64 KiB正文上限、
每条引用的权限/撤销检查、CAS和幂等性。没有删除引用、来源字段或重写G产物。
Runtime986单元通过（11.23秒），Ruff/mypy/build通过。真实PostgreSQL两个原回归通过；
新增1024引用保存/读取、跨项目拒绝、最后一条引用撤销后隐藏正文、回退后拒绝大写入但
保留读取、再次升级测试通过（7.41秒）。首次测试配置缺少测试DSN而skip、随后对拒绝
状态码误写403而实际合同为409的失败不计作通过，修正断言后重跑新增用例。

`capacity-repair/`记录一次明确的修复后重提：使用原operation_id、相同payload与CAS，
避免未知旧提交引起重复写入；无自动重试。取得关联版本回执及相同head，484引用全部保留。
公开保存含MCP启动/确认1.617414秒；G没有再次调用模型。旧checkpoint/result保持原样。
修复pin为`cdccd06328cd07eb77c2fc3956c3df742c30b2c38ae5aa7ee65a7d3c31c30c5c`。
两组Host bootstrap上限统一从16 KiB放宽到64 KiB，以容纳完整来源和溯源信息。

A在模型调用前失败：8064字节details加分页JSON包装超过8192字节预载响应上限，
`DETAIL_PREFETCH_TOO_LARGE_NO_TRUNCATION`，0模型请求。B继续原定State优先续做。
这项预载配置失败不能算语义失败或A/B优势，也没有据此自动追加G或新评测模型。

B终态已交付，但固定来源断言失败：回答1件（blazer），漏掉应计入的同一双换货boots；
预期2。它只读取session-011首页后结束，未查到boots来源。故闭环保存/恢复已确认，
当前任务语义效果失败，不能算完整产品效果通过。B两请求，input50,328/output120，
50,448 raw tokens；在线93.604747秒。修复批含重启/清理167.916458秒，原G/准备另列。
SIM04共16请求、388,032 raw tokens，无pending或usage违规；原批与修复进程均停止。

### SIM05：普通文件搜索与原G产物复用

轻量Host原先只有逐文件分页与MCP检索。新增可选普通`search_files`：Agent自己给字面词，
在完整合法文件搜索，返回带来源hash/字节位置的局部摘录及分页；不含题目或gold分支。
两组均提供同样能力，不追加语义规划器或强制回查。每次读取前检查资格、下次模型发送前
重新核验上下文依赖；HTTP客户端只复用连接，不缓存权限结论。Lab384及静态/构建通过。

新目录`artifacts/v02-e2e-generality/sim05-file-search-20260907a`独立导入完整来源，并逐项
映射原G产物的来源身份；details/handoff及原44文件字节不变。G模型不重跑，历史337,584
tokens只记一次。公开保存、A/B冷恢复重新取得回执；预载响应界限改为16 KiB，bootstrap
仍64 KiB，并在启动任一续做前验证两种呈现可容纳。新增仅两个本地续做会话，各100万
raw tokens/600秒/64请求；同一固定问题/来源断言，不用Judge，不改写SIM04的错误答案。
这是看过失败后的开发增量，不能声称留出效果或单因素跨批提升；实际终态见execution-result。

SIM05已结束，`terminal-audit.json`确认公开保存、独立State身份及两个新进程恢复、同一完整
文件manifest和484条引用。两组都有普通文件搜索，实际均未调用；只读取session-011首页
即交付“1件”，漏掉boots，固定来源断言均FAIL，其他未评价语义维度继续NOT_EVALUATED。

| 组 | 模型请求 | input | output | raw总计 | 在线秒 | 固定任务断言 |
|---|---:|---:|---:|---:|---:|---|
| A 详细记忆预载 | 2 | 55,114 | 163 | 55,277 | 21.539988 | FAIL：1≠2 |
| B State优先 | 2 | 50,182 | 91 | 50,273 | 20.307988 | FAIL：1≠2 |

准备36.290195秒；含准备/保存/两会话/清理81.088161秒。新增4请求、105,550 raw tokens，
无pending/违规。State优先本对照少5004 raw tokens，但两组均错，不证明合格任务上的收益。
与SIM04同时改变了Host连接处理和工具能力，跨批时间差不作为单因素效果或产品SLO。
所有本批模型、API、worker进程退出，PG停止无OOM，共享MCP/vLLM保持原样。

SIM01–SIM05累计41次生成、783,629 raw tokens，7个模型会话执行完成、2个模型会话失败，
另1个分配在首次生成前失败；不将执行COMPLETED等同于语义PASS。付费0，G只计一次。
批次配置关闭，用户继续完成Goal的授权和宽预算开发偏好保留。下一步问题是来源覆盖核验，
而非继续扩大额度或预先增加Hint/reviewer。Goal仍IN_PROGRESS，正式D4/D5未进入。
结论仍限定为本地Host和已打开开发材料；严格成本收益、留出迁移、多租户公平和正式D4/D5
仍需各自证据，单链跑通不自动完成整个Goal。Schema保持NO-GO FOR SCHEMA FREEZE。
