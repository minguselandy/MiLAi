# MiLA V02 组合实现的完整读取 CPU 确认

状态：`FULL_REQUEST_COST_MEASURED / CONCURRENCY_GAP_REMAINS`。实际日期2026-09-07，
文件日期沿用冻结批次。源码未改，pin仍为
`82e0bf3488d65654eaa87ad25a22577b9342366c4eab6c01d1c6f40ec3732321`。
完整P1/P2/P4及D4/D5未完成；没有新增Agent效果或通用性结论。

## 测量边界

Product自身通过真实Flask路由、鉴权和PG执行；复用h保留的1000条完整来源及原请求，
仅启动自有PG，原API/worker/MCP未启动。CPU affinity为0–1，并发最多8，未扩大资源。
一次预热、一次普通单请求、并发8请求和一次单独profile，共11请求。每次完整
MemoryContext均与预热相同，预热也与h原始完整Context相同；没有删除/规范化字段。

这是Product内部开发诊断，不是Lab黑盒、HTTP/MCP网关SLO或新的公开P95校准。
材料位于Product忽略目录`runtime/var/v02-combined-read-cpu/`。所有请求均PARTIAL；
原有信息不足/Context预算边界保留，不因响应200而宣称模型正确或任务完成。

## 整条读取成本

| 条件 | wall ms | CPU ms |
| --- | ---: | ---: |
| 普通单请求 | 113.925 | 74.031 thread CPU |
| 并发8的每请求范围 | 555.618–763.711 | 90.743–121.377 thread CPU |
| 并发8整批 | 775.857 | 774.345 请求thread CPU之和 |
| 并发8进程区间 | 同一批次 | 874.952 process CPU |

进程CPU还含其他线程与调度等开销，不与请求CPU之和相加。这里是一次有界批次，不报告
稳定吞吐/P95或独占GIL根因。当前完整请求工作量仍不支持300ms目标，不能据此宣布P1通过。

历史f上的同类诊断为单请求181.522ms wall / 141.114ms CPU，c8整批1334.481ms，
请求CPU之和1290.801ms。当前绝对成本更低，但两个时点之间还包含日期信号、事务身份
设置等变化，数据实例和运行时点也不同；不能把差值全部归于最近文本/绑定两项修改。
这不是新的同时间配对消融。h的正式公开c8 P95 1306.270ms失败记录继续保留。

## 纠正深复制剖析的误导

单独profile请求CPU为287.613ms，普通请求仅74.031ms，观测开销明显。profile记录
128281次函数调用，deepcopy及递归约77ms，不能把该值当作正常请求的可节省成本。

追加1个预先声明的真实请求，仅在retrieval/memory_resolve外层deepcopy调用计thread
CPU，不改递归实现：60次候选复制合计2.195ms，另一处复制0.503ms。完整Context相同。
至此12个Runtime诊断请求；追加请求及清理单独记录。

静态消费者核对：候选集合供intra-source、按条件启用的instance-preserving admission及
continuation使用；access outcome还维护独立的候选视图。深复制保护可变对象隔离，不能
因为本次某个消费者未启用就无条件删除。未采用删除复制、共享可变嵌套对象或丢弃材料。
即使忽略隔离问题，实测约2.7ms也不足以修复并发差距。

## 当前阶段外层计时

继续使用现有函数入口测量阶段，先预热再观测。第一次脚本在完成预热后因Executor类名
误写而终止，未进入阶段测量；错误日志保留。修正诊断后声明新的2请求上限，成功取得
一条观测。故本轮实际累计15请求（11+1+1+2），不是预先几份计划上限简单相加。

完整请求110.197ms wall / 71.627ms CPU，完整Context与预热及前次相同：

| 阶段 | thread CPU ms | 包含关系 |
| --- | ---: | --- |
| retrieve | 60.547 | 包含获取、快照及其他读取工作 |
| acquisition | 33.795 | 包含下面两个probe、fusion、投影、解释与绑定等 |
| 两个probe | 3.762 / 3.777 | 各wall为16.545 / 16.305ms，含来源获取和排序 |
| fusion | 2.600 | 获取内部 |
| span projection | 9.635 | 获取内部 |
| interpretation | 7.339 | 获取内部 |
| binding | 4.803 | 获取内部 |
| decision snapshot | 15.944 | retrieve内部 |
| access outcome | 0.545 | retrieve之后 |
| Context compile | 7.901 | retrieve之后 |
| 最终JSON输出 | 0.946 | 完整请求内；另有0.020ms测试客户端请求编码 |

嵌套行不能相加。这些外层计时确认快照为当前明确的剩余CPU项；不会把递归profiler的
deepcopy排名当成它的替代证据。原始记录为`stage-timing.json`，失败及修正计划/日志分别保留。
没有新增模型/Provider tokenize或公开校准。

## 收尾与下一步

自有PG经inspect确认停止，客户端关闭，数据保留，共享服务未改。源码/公开配置未变，
无需重复上一轮Runtime1055/Lab309回归；本轮核验诊断断言、pin、原始结果与文档一致性。
无API/schema/权限/事务变化，Schema保持`NO-GO FOR SCHEMA FREEZE`。

下一步核对decision snapshot的规范化、摘要计算及实际消费者，验证能否在完整快照和
规范化摘要字节不变的前提下减少重复工作。保持对象隔离、完整来源及停止线；不凭递归profile排行榜继续微调，
不因局部成本下降重开1000条预置直至偶然通过。
