# MILA-V02-05：日期必要信号检查

状态：`LOCAL_EQUIVALENCE_AND_C1_CONFIRMED / C8_P95_MISSED`。

## 消费者审查与改动

普通LOOKUP的解释和绑定仍进入requirement state、候选来源归属及decision snapshot；
候选也由intra-source shadow、实例保真admission和continuation使用。直接删除解释或将
全部深复制改成浅复制没有获得合同证明，本轮未采用，也未开启另一条type-directed策略。

`evidence_semantics.py`只增加现有日期规则的必要条件：每种规则都必须含十进制数字，
或月份/星期名、ago/today/yesterday/weekend中的完整词。规则清单统一为`_DATE_PATTERNS`；
词表复用已有月份/星期映射。`_DATE_SIGNAL`使用与原规则一致的Unicode数字/词边界/re.I
行为。信号为阴性时日期range及首match映射均为空；阳性时仍运行全部原规则。阳性不是
日期、事件时间、Evidence或答案；未改变解析优先级、日期数字排除或无效日期行为。

此优化按可证明的规则必要条件减少扫描，不改变Source、允许范围、首尾正文、candidate cap
或上下文预算，不保存跨来源/跨请求缓存。若以后增加新的日期语法，必须同步核验其必要
信号覆盖；这不是可以不维护的自然语言完备词表。

初步局部试验拒绝了“合并全部日期regex”的方案：8192字节无日期文本约1.283→1.252ms，
改善很小；8014字节含日期文本约1.258→2.486ms。必要信号候选在同类无日期长文本中明显
减少扫描，但长文本末尾有日期时约1.264→1.481ms，增加一次信号检查成本。这些为探索性
单函数平均，不是正常请求或服务性能结论；生产代码未加入被拒绝的组合正则方案。

## 等价与局部成本

新增12个参数化控制覆盖无日期长文本、普通说明、Unicode数字、嵌入数字日期、多种日期
及相对词、特殊Unicode大小写、相近但不匹配的词边界和首尾日期；逐一对照原规则所有
range与首match。连同原日期、语义、type-directed和formation控制50通过（0.73s）。
Ruff首次对测试中的刻意Unicode字符报警；只为这两行加入说明性的RUF001排除，没有
改变测试内容或产品字符处理。最终Runtime Ruff/mypy（189文件）/build通过。

Product内部诊断复用已停止f的自有PG及1000完整来源，正常reader认证/binding/路由及
scope/预算不变；原API/worker/MCP未重启。预先固定2请求，预热时对真实240个span同时
运行修改前后解释，随后恢复正常函数profile。完整候选和suppressed计数相等，新请求的
完整Memory Context与上一轮同数据请求逐字段相等，无字段或ID删除。

对这240个片段交替先后顺序各10次局部非profile计算，完整结果始终一致；解释中位
55.525→27.383ms。记录在Product `runtime/var/v02-date-signal/`，修改前源码保存在
`runtime/var/v02-c8-cpu/evidence_semantics_before_signal.py`。这批片段的分布不代表任意
任务；含日期材料可能只有额外检查成本，不宣称所有输入都变快或算法语义效果提高。

## 固定运行身份与确认

新锁`data/locks/v02-date-signal-product.lock.json`，源码pin
`49ed9d3fe7fcc9d856b110e026902c0135899d9eab261168d67e80a1aa377b74`，锁digest
`8fe4fb4638c2f035ca0d0d7421d064cc31dd1d1be78014edf82e910b8266a2aa`。
当前E2E/SIM02候选同步pin，历史配置与失败记录保留。公开配置
`configs/v02-scoped-recall-date-signal.json`仍为1000来源/两项目/完整三种长度/相同预算，
读取并发1/8、每轮24、三轮、300ms停止线，就绪5秒，预置并发4和原资源上限。

Runtime真实PG完整回归1034通过、无跳过（95.76s），记录在
`artifacts/v02-e2e-generality/p1-date-signal-regression-20260906a/`；新自有数据库，SDK路径
预先配置。Lab309通过（2.56s），边界/Ruff/mypy/build通过。MCP/SDK源码未改，未重复旧回归。

```bash
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall-date-signal.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906g
```

公开g运行20批就绪、范围正例、外项目MISS和伪造scope拒绝通过；1000来源输入hash、完整
catalog与f相同，首个完整MCP响应只规范化新Evidence ID/context_id后与f相同。

| 阶段 | 读数 | P50 ms | P95 ms | P99 ms | 完成/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| c1-r0 | 24 | 201.046 | 226.462 | 238.089 | 4.857 |
| c1-r1 | 24 | 197.007 | 224.900 | 276.355 | 4.875 |
| c1-r2 | 24 | 191.902 | 226.731 | 245.145 | 4.990 |
| c8-r0 | 24 | 1196.758 | 1400.010 | 1417.726 | 6.237 |

c1均通过300ms线，c8仍超线并停止后两轮。相对f观察到延迟下降，但仅同配置各一批，
不能扩称任意来源或全部延迟改善由本优化独占解释。MCP99次，其中97预算受限视图、
1MISS、1预期拒绝；SDK1021次，Runtime HTTP1125（201×1000、200×125），层次不相加。

Runtime98次resolve的application P50/P95为156.512/1172.972ms；连接持有之和
45.139/669.168ms，池获取之和最大81.704ms，连接外剩余107.822/591.959ms。只报各层
分布，不按顺序强配MCP或减P95。连接持有部分仍大，不能把后续问题全部归于日期扫描。

## 收尾与下一步

自有API/worker/MCP均不存在；公开、回归及剖析复用PG均经inspect确认停止，数据保留，
共享服务未动。完整P1仍未通过。下一步先用现有事务进入/退出及连接计时拆解剩余持有
区间，结合已确认CPU需求检查必要调用，避免继续只优化一个小正则或增加并发参数。

本轮没有API/schema/权限/Canonical/事务/迁移变更；
Schema保持`NO-GO FOR SCHEMA FREEZE`。新增模型/Provider tokenize均0，完整P1/P2/P4
及D4/D5未完成。
