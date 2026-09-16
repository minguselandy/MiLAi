# MILA-V02-05：千条来源范围检索与有界呈现

状态：`SCOPE_CONTROLS_CONFIRMED / SINGLE_CLIENT_P95_MISSED`。
补齐了公开MCP范围读取的一段证据；单并发首轮P95为330.880ms，未满足冻结300ms门槛，
后续轮次与并发8未进入。不是完整P1、网关SLO、租户隔离或模型效果通过。

## 本轮改动与设计选择

只读核查当前安装的MCP `ToolManager.list_tools`、`MCPServer.list_tools`和MiLAi
`_StrictSchemaMCPServer.list_tools`：每次会创建列表、协议Tool及schema浅拷贝；工具管理器
支持增删，协议路径要求当前调用者可见的catalog。此前服务端GC证据没有定位这些分配为
具体热点，因此没有引入catalog缓存、绕过协议检查或修改GC策略。该诊断支线暂不扩展。

Lab扩展既有`check_v02_e2e_live.py`，新增`check_v02_scoped_recall.py`，继续通过公开SDK
预置和公开HTTP MCP读取。Product源码未改，pin保持
`13999df2432148b9ec9cd2580164f3cae70ee2875b70a2a8dff316f5a0b3ce46`。
没有Product私有调用、SQL写入、新Memory实体、Schema/权限/Canonical/事务语义变化。

## 冻结条件与两次执行

两个独立新服务各预置1000份Evidence，项目各500份；512/2048/8192字节轮换，首尾保留。
相同公共词用于范围查询，每份另有唯一标记；MCP绑定`mixed-project`，另一项目来源不可读。
所有1000个来源请求正文hash在两次运行间逐一相同，完整来源未为通过检查而缩短。
20个公开就绪批次均确认`evidence-search-v1`已就绪，不以保存回执冒充索引可见。

API线程/连接池最大8、PG 2 CPU/1 GiB、进程CPU affinity 2核、预置并发4；最大读取并发8。
BASELINE、Evidence dense关闭、无reranker，使用确定性16维hash投影；无生成、收费依赖
或共享vLLM调用。计划并发1/8，每档3轮各24读；闭环客户端计时，P95停止线300ms。
来源预置、就绪与三个范围控制另记；不是固定到达率或网关测量。

```bash
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906a
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall-bounded-view.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906b
```

**a保留为失败。** 首个公开查询耗时387.383ms，返回8条允许项目Evidence，未发现外项目ID或
唯一标记；因`DEGRADED`被初版检查器拒绝，其余检查未进入。实际唯一警告为
`The returned memory context was limited by the context budget.`，不是已确认的组件故障。

随后在b运行前冻结评测修正：仅当存在合法Evidence，且唯一警告明确为上述上下文预算限制时，
允许继续计量，单列为预算受限视图。其它降级、未知状态、缺少必要召回或越界仍立即停止。
这符合Context有界且有损的设计；不是将降级改成完整召回PASS。a文件及结果未改，b配置记录
修正理由，来源/读取预算/并发/300ms阈值均未变化。两次不是优化前后效果对照。

**b实际结果：**

| 项目 | 观察 |
|---|---|
| 正常范围查询 | 返回允许项目Evidence，预算限制提示单列 |
| 外项目唯一标记查询 | `MISS`，无外项目正文/ID披露 |
| 伪造`requested_scope`工具参数 | 工具返回预期错误；未扩张绑定范围 |
| 并发1首轮24读 | 全部返回合格但预算受限的视图；P50 269.461 / P95 330.880 / P99 338.597ms |
| 首轮吞吐 | 3.561完成/s；闭环观察，不是容量结论 |
| 后续两轮与并发8 | 未进入；没有提高负载或重跑直到通过 |

b共27次MCP工具调用：25个预算受限视图、1个MISS、1个预期拒绝。所有返回Evidence ID都属于
预置的允许集合，检查也覆盖响应其它字段中的外项目ID/唯一标记。此证据仅覆盖一个可信MCP
绑定、两个项目、同一Runtime租户；不能扩称跨租户公平性、全部500份来源召回或语义理解。

## 成本、已有计时与限制

两次各1021个SDK物理调用（1000保存、20就绪、1 capabilities）；Runtime分别1027/1052个
HTTP请求（含服务辅助调用，均200/201）。MCP分别1/27次，三层调用数不能相加。
新增模型生成、Provider tokenize、本地模型分配均0。

b的公开Runtime计时包含26次resolve：application P50/P95为222.014/284.278ms；
连接持有时间之和P50/P95为44.027/51.308ms，池获取之和最大0.208ms；application减去
连接持有与获取后的剩余区间P50/P95为173.976/241.664ms。25次各7个连接区间，1次9个。
这使下一项核查指向Runtime连接之外的检索后处理、装配及预算计算，而非先加大数据库池。
剩余区间不等于CPU耗时，未定位具体函数或证明优化收益。

MCP呈现未暴露Runtime request ID；本轮只报告Runtime与客户端各自的分布，没有按时间
顺序强配请求，不能相减两个P95声称网络耗时。完整可复核计数见各运行`final-observation.json`。

## 检查与收尾

初版相邻10、Lab完整305通过；修正规则后相邻14、Lab完整**309 passed（2.53s）**。
两版的Ruff/边界/mypy/build均通过；Product源码未改，不重复其历史检查作为本轮结果。
每次运行已确认自有API/worker/MCP进程不存在、PG停止并保留数据；共享服务未触碰。
无迁移、部署或外部写入，Schema仍`NO-GO FOR SCHEMA FREEZE`。

下一步只核查单并发范围读取在Runtime连接之外的主要工作，定位后再决定最小修复和同条件
确认；保留State长尾和本轮范围读取门失败。D4/D5未进入，Goal未完成。
