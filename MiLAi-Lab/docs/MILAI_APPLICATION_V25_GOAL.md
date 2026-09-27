---
status: ACTIVE
scope: RESEARCH_PROTOTYPE
parent: MILAI_LONG_HORIZON_EXECUTION_GOAL.md
reference_commit: 1053719dc004c1a630abac0195f0ce1f290ac6a3
---

# P12：持久化应用与同域质量—成本比较

执行总计划§20、§24、§30、§43。v24的F/R提示家族已因没有必要行为收益而停止。本阶段使用普通LangMem Agent和冻结v21 SER；不启用F/R，不把用户明确要求的记忆更新算成自主生命周期收益。Product、旧M1/ODR和vLLM设置保持。

开发一个非benchmark有状态应用：SQLite业务世界按用户隔离，工具从实际提交的数据生成回执。一次reserve先提交预留记录，随后因标签服务不可用而返回ok:false及已发生的副作用。下一独立进程读取原记录并完成标签；不能用静态fixture回执冒充恢复。业务工具接受合法但可能不符合当前记忆的参数，不能读取rubric或自动校正动作。

五个进程阶段共九条公开消息：

1. 通过上游manage工具给Alice保存主计划、访问事实和旧联系人，给Bob保存同名物品的另一计划；两人各实际search并总结。
2. 操作员通过相同公开工具更新Alice主计划至revision2并删除旧联系人；Alice再次实际search并形成结论。
3. 操作员更新Alice计划至revision3；Alice先处理一条无关的一次性日志，再按当前计划仅尝试一次reserve/label。服务不可用，实际预留副作用应保留。
4. 新进程恢复标签服务；Alice读取并完成已有预留，不重复reserve；Bob按自己未改变的计划完成一次操作。
5. 两人各开新session。Alice搜索计划并读取业务现状，明确要求更新原记忆为实际返回状态/identifier；Bob搜索并报告自己的未变计划。

阶段间关闭并重新打开Provider、Store、sidecar、checkpoint和业务数据库。相同session保留历史和public_index，新session只有同用户Store持久数据，不串用旧checkpoint。公开操作员CRUD的ID由工具返回绑定alias，不能按领域词定位或直接写产品/Canonical表。操作员与Host调用分别标记来源，全部embedding计费。

已完成journal调用重放不能重复副作用。业务提交至journal持久回执间崩溃的结果明确UNKNOWN，不自动重试；不假装提供跨数据库exactly-once保证。必要离线测试覆盖partial write/reopen/read、已知重放与未知边界、用户scope和阶段恢复、四臂实际请求接线。

先冻结短脚本的相同输入和独立rubric，再运行B1→A3→A4→A5，每臂新namespace与业务世界、五个串行进程，真实模型/embedding并发1。A3/A4保持无上限exact refresh，A5保持既定rank/current策略和每search最多1次；普通Host容量12生成/公开消息不提高。所有失败、partial side effects及错误最终表述保留，不能选择最好轨迹。

评分分开列出：公开任务完成、首次动作参数currentness、重启恢复与不重复副作用、真实CRUD内容、删除/无关信息保持、跨session与用户隔离。以原SQLite状态、实际HTTP/工具回执、Store内容和checkpoint为依据。rubric只在运行后评分，不进入runtime。四臂同一脚本报告质量—成本Pareto，不能用P9三臂正式结果拼接A5开发成绩。

统计全部生成输入/输出、embedding、exact reads、投影CPU/wall、observer成本、持久化大小和进程/Provider延迟；用户显式搜索/操作员更新与方法读写分别列出。继续`artifacts/ser-v20/budget.json`，起点671生成/604171tokens/6104embeddingtokens/75exact reads。没有新增总cap，也不因此扩大开发样本。

全部应用开发完成后，再冻结同一脚本的medium/long历史边界，初始仅B1/A4配对，避免四臂全因子扩展。真实搜索和模型结论与合成无关日志分别标注；不宣称填充日志等价于自然长程使用。主未见效果未建立，§42广泛鲁棒性仍不启动；§19第二模型独立端点待补充，不阻塞当前开发但不能冒充已完成。

源码由原Sol xhigh实现，Root负责公开fixture/rubric/协议、冻结、真实调用和分析，Luna high负责提交推送。共用现有资源管理和普通Agent，不依赖benchmark loader/评分器；不为新脚本创建通用平台。每阶段失败先定位first broken link和两个可区分解释，必要修复重新冻结，保留旧成本。

- [x] 持久业务世界、通用资源接线、阶段运行器和四臂入口。
- [x] 原始公开输入/rubric/协议与必要窄验证，源码锁和一次构建。
- [ ] 短脚本四臂实际运行、全部语义结果和费用。
- [ ] 必要medium/long边界及已覆盖/未覆盖项。
- [ ] Failure Review、十项Reflection、同域Pareto及复现。
- [ ] Luna提交与远端核对；总Goal继续完成剩余证据要求。

源码已冻结：81文件mapping `ff874dc00936261303336963a415007ddbe93bbdf06a87cb87ae0a7409ab6e38`，lock SHA `796b32df3dbe5d5028d799bbdd92a7ff313ac17fd73ce34a84de3cae3d4d0e25`。六项新窄检查、一个受影响旧fixture观察器检查、ruff/mypy通过，尚未真实调用。mock Provider经真实ToolNode执行时发现SQLite默认线程绑定错误，已改为允许工具线程访问并以小锁串行业务调用；实际部分写入/重开/用户隔离验证通过。没有修改SER算法、JSON-action传输或vLLM设置。

唯一必要构建通过：sdist SHA `e8159a5a8c1b9f5403ec0b3da143fbd15d4bf18bb81908dbb4431781e3faf530`，wheel SHA `fd3f3ad4acdf20c9236d6abe9feb98f61913f6f83df93aa27e030da45e6c6dbc`。短/中/长公开脚本与冻结文件均进入sdist，新runtime进入wheel，未包含private/generated产物；锁后源码不变。后续结果文档不触发重复构建。
