# MILA-V02-05：请求内快照摘要按需派生

当前结论：普通读取不消费完整快照摘要，先冻结材料、按需计算可减少这部分 CPU；
完整内容和逐请求快照对照成立，并发目标仍未达到。运行发生于2026-09-07（Asia/Shanghai），
文件名沿用本轮20260906标识。最终检查与pin记录在本文末尾。

## 证据与实现边界

旧pin `82e0bf3488d65654eaa87ad25a22577b9342366c4eab6c01d1c6f40ec3732321` 下，
Product自身1个真实Flask公开路由/认证/PG请求，记录返回后的属性消费：只有
`lean_recall_mode`、`evidence_set`各1次，无摘要读取；完整MemoryContext与保留h相同。
静态检查确认Reader的plan/render、Audit observer及回放路径仍需要完整快照。

实现仅调整内部派生计算时机：

- 决策事实仍立即经过原有集合/引用约束校验，材料在当前请求内规范化并冻结。
- 普通MemoryResolve在Context编译器无需完整快照且未配置intra-source时请求延迟摘要。
  未知编译器能力保守使用原有完整路径；直接Retrieval调用默认也保持完整路径。
- Audit observer和matched replay强制完整快照；Context plan遇到延迟对象时先取得完整快照。
- 摘要仍使用原有canonical JSON和SHA-256，单对象锁保证并发消费者只完成一次派生，
  完成后释放保留材料。没有跨请求缓存、空摘要、假版本或新的数据库Memory实体。
- 不可JSON编码的内部摘要材料在完整派生时抛出原错误，不伪造成功摘要；事实校验和
  已有权限/范围检查不延迟。完整路径仍立即编码。这个错误时机差异明确保留。

普通Source/Gate/Binding/解释、完整候选/首尾正文、Context和trace能力未删除；没有修改
CAS、回执、Canonical治理、身份或披露规则，无migration或部署变更。
`DecisionFacts`只是内部已校验值对象，不是Host State、Canonical State或新存储层。

## 冻结失败及修复

第一候选pin `6a3484d1ee505e397539950fb9fe6dd6d43cd14354c181e66b0d35e5d42744da`
通过真实输入和标准Pydantic对象检查，但追加控制发现自定义`model_dump`可能返回源对象
别名，修改源对象会改变延迟摘要。该失败记录为`alias-control-failure.json`，未删除。
修复为显式复制自定义/覆盖序列化输出；Pydantic标准JSON序列化仍使用其独立输出。
同时覆盖duck-typed序列化和BaseModel覆盖方法，两种源对象修改均不改变已冻结摘要。

开发中一次字段移位遗漏、一次属性名拼写和mypy的动态构造类型错误均在局部检查中修复；
没有失败后的隐式模型调用。曾考虑的独立JSON递归校验没有采用，避免复制内部编码器。

## 同输入成本与内容

Product自有捕获材料来自完整h数据，`trusted-inputs.pickle`只由本任务自身生成与读取，
不是公开输入，也不进入Lab黑盒。每个计时项10次交替测量，完整结果在计时后核对。

| 实现 | 立即完整快照CPU中位ms | 仅冻结与事实ms | 随后需要完整快照的总ms |
| --- | ---: | ---: | ---: |
| 第一候选 | 14.734 | 2.954 | 14.667 |
| 修复自定义输出所有权后 | 14.743 | 3.196 | 14.790 |

最终三个路径tracemalloc峰值依次为4286960、690146、4305136 bytes；这不是服务RSS。
延迟路径16.707ms单次离群值保留，未归因于未观测的GC或其他原因。所有材料语义、完整
快照字段值和canonical摘要一致；没有把JSON对象字段插入顺序当成字节稳定合同。
局部CPU节省不代表Agent token下降或语义质量提升。

## 真实请求与容量限制

第一候选复用h的1000完整来源、原认证与scope，执行预热1、单请求1、c8共8，合计10。
affinity仍0–1、总连接池上限8，系统报告两逻辑CPU为同核SMT；不调整资源或扩大负载。
全部HTTP200/PARTIAL，完整MemoryContext与历史h相同。10次请求均未消费摘要，计时结束
后针对各自同一输入完成完整快照与摘要等价检查。

- 单请求102.280ms wall / 62.945ms CPU。
- c8各请求493.635–660.821ms wall，整批682.563ms。
- c8请求CPU之和635.418ms，进程CPU732.142ms；这些是包含关系，不相加。
- 快照阶段各请求CPU3.867–5.232ms。

这些是Product内部Flask/真实认证/PG诊断，不是HTTP/MCP公开SLO。旧组合诊断单请求
74.031ms CPU、c8整批775.857ms可作背景，但不是重复随机化比较，不能据此估计稳定效应。
修复输出所有权后另1个真实请求确认最终语义候选的完整Context、未使用摘要和同输入
完整快照，未再次运行c8。公开校准仍保留h的P95 1306.270ms失败结果。

本增量总计12个真实诊断请求（旧消费者审计1+首候选10+修复后1）。工程回归的API调用
另属于测试执行，不混进诊断分母。模型生成、Provider tokenize、公开SLO校准均0。
所有自有诊断客户端关闭、PG停止、数据保留；共享vLLM/公开MCP未触碰。

## 检查、pin与后续

第一候选真实PG回归1065通过（97.24s）；所有权修复语义pin
`d8a1b462b6359ca453ab27b1a1bfc8ed72640a084632ce1937d601b7152b554f` 的完整真实PG
回归1067通过（96.38s），无跳过。使用隔离新PG、原有测试角色及Runtime的`pytest -q`，
SDK/OpenWorker路径仅供Product自己的集成测试，不把它称为Lab黑盒效果。

最终pin `d6343d4b34c1f85ab40780cd12f4ac89fb5e34b3055b4d99edd8d1fb8084f337` 只额外
修复一处E501换行；`format-equivalence.json`确认该文件AST相同，其他源码无此阶段变更。
最终`uv run pytest -q tests/unit`为889通过（10.85s），`uv run ruff check src tests migrations`、
`uv run mypy`（189文件）及`uv build`通过。没有重跑仅因换行而无语义变化的PG全量，
不把之前的pin写成最终字节pin。新增12项用例覆盖事实校验、材料别名/变更隔离、并发
派生、错误传播、完整Reader/Audit/replay消费；旧有权限和数据库回归保持。

Lab本增量`uv run pytest -q`为309通过（2.60s），`uv run milai-lab-check-boundary`、
`uv run ruff check src tests tools`、`uv run mypy src/milai_lab`（30文件）和`uv build`通过。
最终E2E及仍关闭的SIM02候选配置分别验证新lock有效：
`data/locks/v02-lazy-snapshot-product.lock.json`，lock摘要
`b30f0427baed739da3fc620b6121fbee220b31198eaea6993955dbb43f572ef0`。
历史两个候选lock与诊断/失败材料保留。无外部API/schema/权限/Canonical变更；回退是恢复
原有内部立即派生路径，不需要数据库降级。尚未完成公开容量和模型效果验收。

原始诊断：Product `runtime/var/v02-snapshot-consumers/`。
首候选回归：Lab `artifacts/v02-e2e-generality/p1-deferred-snapshot-regression-20260906a/`。
所有权修复回归：Lab `artifacts/v02-e2e-generality/p1-snapshot-ownership-regression-20260906a/`。

后续先检查剩余普通读取的重复获取及阶段消费者，只有完整输出等价且具有实际收益才改；
不靠增大连接池、换CPU或删除源材料解决预算失败。完整P1/P2/P4仍未验收，D4/D5未进入，
新增模型授权仍0，Schema保持`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
