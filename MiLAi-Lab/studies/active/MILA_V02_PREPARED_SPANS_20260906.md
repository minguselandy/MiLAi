# MILA-V02-05：共享机械准备与按需span构造

2026-09-07（Asia/Shanghai）执行，沿用20260906标识。最终Product pin：
`8e345a71f73f69277d68dc0e85016219f53c7a847767593ddc37c48601b5d97f`，
锁`data/locks/v02-prepared-spans-product.lock.json`；E2E与仍关闭的SIM02候选引用新锁。
历史10f锁、失败结果及原始来源均保留，模型/token授权不变。

## 最终实现

当前普通读取只使用部分raw诊断事实，却先构造全部span，再深复制给snapshot。
现在复用原`defer_semantics`资格条件：普通模式、非typed、无Formation、无operator、
无range scan时，准备准确分句偏移并为每个有span的来源构造首个真实span。
资格、身份、时间、元数据、首个真实偏移及源文核对立即完成；其余对象与内容摘要在完整
消费时构造、验证。正文非空不再被当作span存在性。

`evidence_semantics.py`抽出共享来源准备与单span构造，原完整投影和新
`PreparedEvidenceSpans`使用同一实现。新对象拥有验证后的元数据与完整源文；snapshot
深复制其准备材料，完整消费沿原排序及去重顺序返回完整DTO，锁保证一次构造。
审计、回放、typed/严格操作等原路径保持完整计算。Context、原文、首尾、权限读取、
公开字段、Canonical、CAS及数据库schema均保持，无migration或共享部署变更。

## 候选控制与修复

Product忽略目录`runtime/var/v02-prepared-spans/`保留候选与离线记录：208正文、36元数据
控制及60实际来源/240span完整比较通过。随后补查发现去重必须发生在原投影排序之后；
逆序时间的重复来源会令初版候选保留错误版本。该失败保留，增加9个重复/时区控制，
候选改为复用原排序与去重后再进入实现。

实现自查又发现：完整列表返回后被清空，准备对象仍沿用旧布尔值。修复为已构造后使用
实际列表；诊断非空判断也重新检查实际文本，保留“列表非空”和“有非空文本”的区别。
增加清空/改为空白的冻结控制。此前预检查主动中止，退出2、671通过不能算全量通过；
保留于`p1-prepared-spans-regression-20260906a`，其初始pin为000a43cc…。
最终8e345a71…在新独占数据库重新全量验证。

## 最终实现的收益与延后成本

`runtime/var/v02-prepared-spans-final/`包含最终同pin对照。交替10轮、相同捕获输入，
两边都延后raw语义，仅改变是否提前构造全部span：

| CPU中位 | 提前构造 | 准备后按需构造 |
| --- | ---: | ---: |
| 编译＋snapshot准备 | 14.957ms | 8.972ms |
| 后续完整DTO＋snapshot消费 | 48.022ms | 53.694ms |

全部DTO、字段及snapshot/摘要相等。后续消费成本单列，不能把延后工作当成永久消失；
此对照不包含数据库和Context编译，也不是Provider token或模型效果实验。

最终10次真实Flask公开路由/认证/PG请求（warm、single、c8）保持完整Context；计时后
各自的完整DTO/snapshot均与完整路径相同，请求内确实未消费剩余span或raw语义。
单请求wall/CPU77.909/39.293ms；内部c8整批443.655ms，请求CPU合计397.596ms、
process CPU496.768ms，仍未达标。保留79.236ms CPU较高样本，不相加不同观察边界。
候选另有10诊断请求，合计20；候选结果不冒充最终实现结果或公开MCP SLO。

## 公开复测k

配置`configs/v02-scoped-recall-prepared-spans.json`；原始记录
`artifacts/v02-e2e-generality/p1-scoped-recall-20260906k/`。
1000条capture body摘要、工具目录与j相同，完整源文512/2048/8192及首尾保留。
同核SMT 0/1、PG2CPU/1GiB、池8、最大并发8、原Lab全字段检查及整体300ms门槛不变。

| 轮次（每轮24请求） | 整体P95 ms | 收到响应P95 ms |
| --- | ---: | ---: |
| c1-r0 | 117.652 | 111.319 |
| c1-r1 | 108.361 | 101.978 |
| c1-r2 | 109.625 | 101.303 |
| c8-r0 | 574.697 | 563.730 |

c8首轮超标，后两轮未执行；分位数不相减。j的662.906ms仍为历史结果，单次顺序复测
不推出所有任务或负载下的加速比例。20批readiness与3个项目范围控制通过，不作租户公平性
结论。MCP99包含97预算受限DEGRADED、1MISS、1预期拒绝；SDK1021；Runtime1125，
其中1000×201、125×200（resolve98）。层级计数不相加，DEGRADED不记HIT。

## 最终验证与清理

- Runtime新增32控制，最终真实PG全量`pytest -q`：1136通过，无跳过，96.40s。
- Runtime `uv run ruff check src tests migrations`、`uv run mypy`（191文件）、`uv build`通过。
- Lab `uv run milai-lab-check-boundary`、`uv run pytest -q`（337通过，2.73s）、
  `uv run ruff check src tests tools`、`uv run mypy src/milai_lab`（30文件）、`uv build`通过。
- 最终pin再次核对通过；回归证据位于`p1-prepared-spans-regression-20260906b`。

两次回归自有API/worker均不存在、PG停止；诊断h PG停止，原API/worker未重启。
公开k API363945、worker363946、MCP363999已不存在，PG停止，数据保留。共享服务未改。
生成与Provider tokenize均0；服务初始化/回归调用和上述诊断、SDK、MCP计数分别记录。
完整P1/P2/P4及正式D4/D5仍未完成，Schema仍为`NO-GO FOR SCHEMA FREEZE`。
下一步依据新版本剩余请求成本推进，不重复记入已经延后的投影工作，不扩资源或改门槛。
