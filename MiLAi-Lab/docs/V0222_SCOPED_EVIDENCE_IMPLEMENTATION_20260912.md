# V0222：显式证据读取适配层实施

日期：2026-09-12。状态：`R2_LOCAL_REVIEW_COMPONENT_PROBES_AND_FULL_REGRESSION_PASS / NOT_CONNECTED_TO_BATCH`。
依据已独审的[V2设计](V0222_SCOPED_ADMISSION_V2_DESIGN_OFFLINE_20260912.md)，
保留原设计文件及其hash。本记录补充实际实现、反例和窄修，不变更任何模型/业务合同或发送授权。

## 实际实现与边界

新增`tools/v0222_scoped_evidence.py`及对应局部测试：verify_manifest、verify_tree、read_artifact、
read_pinned_events四入口均显式接受AdmissionReadScope。作者`/root/batch_guard`，独审`/root/v222_review`。
原helper、其46项测试、旧正式Batch/Provider/runner及全部旧冻结证据均未编辑。

语义失败需使整个scope失效，即使调用者捕获异常也不能正常close。适配层只在唯一guard中
显式耦合已冻结helper的`_active/_poison`钩子；不制造假hash冲突，不提前close，也不使用隐藏上下文。
JSONL从同一核验bytes解析，但每次调用重新解析，返回独立对象；不把helper.json_parses当JSONL解析次数。
JSONL分行沿用旧read_events的splitlines行为。四入口不实现57账历史聚合、授权或Batch动态准入。

## R1：局部58项通过，但真实引用树未达标

作者58项局部测试通过（1.27秒），Ruff检查/格式通过。
模块SHA `33858fc52187d376f00131fc0bb2e5399bcefaac0627b7d7a0141f551a299956`；
测试SHA `4fdcd2ca6fe0cb8eabf47475df2e105b91c7f80f7db28ba9b43157a1dc2f16df`。
这些不是全仓2434基线的一部分，也不能替代实际规模结果。

对已暴露旧正式root做四个固定只读入口探针：每入口最多30秒语义预算，异常后仍完成mandatory close。
新子进程仅运行组件，不启动模型、HTTP、Batch事务写入、设备或服务操作。四进程有时间重叠，
因此不是独占资源基准、加速比或完整16＋24阶段时间证明。

| 入口 | 结果 | 首次/收口文件 | JSON解析 | 重复引用 | 总墙钟秒 |
| --- | --- | ---: | ---: | ---: | ---: |
| manifest | PASS | 4547/4547 | 1 | 60 | 2.52924 |
| 全部19 artifact行 | PASS | 5755/5755 | 19 | 9488 | 3.21935 |
| 57固定JSONL | 225事件解析PASS，未验证FSM | 57/57 | 0（JSONL另解析） | 0 | 0.03423 |
| 完整终审引用树 | 30秒语义超时，CLOSED_FAILED | 5865/5865 | 3046 | 146163 | 31.41322 |

树探针未完成，5865只是已访问路径数，不是完整闭包声明；树会额外追踪嵌套manifest副本，
不能把它直接等同于终审顶层5784文件映射。失败源于仅用active recursion stack而未消除已完成子图的重复遍历。
独审另以11文件共享子图复现6129重复引用，说明hash去重不等于语义遍历工作量线性。

同时独审复现：空set子类覆盖`__contains__`返回True，可使root→child→missing-grandchild
在只读前两文件后错误成功。此为R1的真实接口漏洞，不因普通set测试已通过而忽略。

外部目录`/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/`：

| 制品 | SHA256 |
| --- | --- |
| scoped-evidence-r1-source.py（失败单文件快照，不作运行依赖） | `33858fc52187d376f00131fc0bb2e5399bcefaac0627b7d7a0141f551a299956` |
| scoped-evidence-r1-probes.json | `12330abae76595276b230c8aab58e75831881cc52dd00ffcacb14dd02368eb87` |
| probe_scoped_evidence.py（固定root只读探针） | `3af0e77d2b5f3ae06af1f8f03db6bad3b752194ab75c304b3a2172172a777a6d` |

## R2：单次调用内已完成子图去重补充

独立审阅认为下述最小修订可进入离线实施，不构成实现通过或新真实权限：

- public seen只接受None或初始为空的exact set；遍历使用内部真set，调用方无法注入完成状态。
- active与completed分开；completed由每次verify_tree独占创建，只在该节点自身语义及全部孩子成功后登记。
- 每条incoming reference仍调用scope.read_bytes核验其期望hash，冲突不能被completed吞掉。
- manifest在考虑completed之前执行自身源码副本、输入和环境验证；bytes-only成功不替代用途校验。
- 已完成子图只在当前tree调用内去重，不向下一tree、manifest、artifact、history、HTTP或其他scope提供PASS缓存。
- 失败不能留下可用完成标记；重复调用仍须完整验证当次环境和文件；两次内容观察仍不是不可变快照。

这对原设计“seen只终止环”的具体实现作必要窄修，保留不跨用途/不跨准入缓存结论的安全目标。
新增负控须覆盖set子类、共享菱形缺失孙节点、共享节点冲突hash、bytes-only后manifest副本/环境漂移、
两次tree间环境变化及11文件菱形近线性访问。R1失败原样保留；R2另做精确同版测试/独审与有界树探针。

## R2实际结果与当前回归

最终模块SHA `d32a3eedd5776185b021eb0835e2c055a6a60b494f15d86145aa53ff6d110ccf`；
测试SHA `3da48f1e0a76efe163bf79efa5e307bdd6384cebd9a48b9d9e1a9fe8a0a55dbb`。
作者64项测试PASS（1.30秒）；独审同版64＋原helper46＝110项PASS（1.31秒），Ruff通过。
独审重新构造set子类负控已拒绝；11文件菱形重复引用由6129降至41，并验证hash冲突和manifest环境检查仍执行。

| R2实际入口 | 结果 | 首次/收口文件 | JSON解析 | 重复引用 | 总墙钟秒 |
| --- | --- | ---: | ---: | ---: | ---: |
| manifest | PASS | 4547/4547 | 1 | 60 | 2.31374 |
| 全部19 artifact行 | PASS | 5755/5755 | 19 | 9488 | 3.20828 |
| 57固定JSONL | 225事件解析PASS，未验证FSM | 57/57 | 0（JSONL另解析） | 0 | 0.03228 |
| 完整终审引用树 | PASS | 5865/5865 | 5267 | 123105 | 11.55941 |

R2树语义耗时10.12411秒，收口后总11.55941秒，满足此次组件30秒探针界限；这不是1800秒阶段证明。
新闭包路径/hash与旧原函数的精确覆盖对照已独立完成，详见下节；不是只凭5865计数宣称无漏项。
R1超时与接口漏洞保持原记录，不改成R2通过。

| R2制品 | SHA256 |
| --- | --- |
| scoped-evidence-r2-probes.json | `b94d4cbd3dd03f166f292c711ad8d81f94607f0a419b2eab55ad29364ad06151` |
| independent-scoped-evidence-review.json | `8cb45a4bf386bca05552b72371da6035b69842717abed5f2f30382b0083ff441` |

主代理当前版工程检查：boundary PASS（8fac04）、Ruff PASS（a4907a）、Mypy39源PASS（c5b13b）、
build PASS（session10934 terminal f4b538）。全仓pytest session89818现已terminal0（09c40c），
2498 passed／1 optional Host SDK skip，1209.05秒。四个scope/adapter源码与测试hash保持不变。
工程制品`scoped-evidence-r2-engineering-checks.json` SHA256
`3df4a8128e3cfdcf50da262a432c3b10692286fa778c7ccce849725ff3fc6983`。
原2434组件基线保持为此前版本证据；此2498基线仍不覆盖随后新增的history代码和测试。

## 完整闭包独立对照与解释纠正

`independent-scoped-closure-review.json` SHA256
`dafbe37a86c1de04bbab2817ef8c9718c033f2e42617e60d385e40d39f4e8aa2`：
旧显式图及8份manifest隐式源码/输入/264执行副本扩展后的完整映射，等于新首次及新收口映射，
均5865项，缺失/多余/hash差异全0。主代理再次重算5868项制品依赖hash通过（chunk4bb7dc）。
结论只对这个固定根成立，不代表所有未来图或Batch动态状态正确。

精确集合差表明：相对顶层5784文件，多出的81项为终审文档自身＋80个更旧的冻结offline World数据库，
不是新增执行副本；264份执行副本本就在完整显式图内。递归闭包共160个固定World数据库，
动态中央batch.sqlite/WAL/SHM均未纳入。R2探针制品limitations/3先前对“多出的文件来自执行副本”
作了未经集合证明的推断，现以追加`scoped-closure-explanation-correction.json`纠正，SHA256
`104b5990100665a8c147385a32eb7dbdc3517104bf89678b39d43e569835ee48`；原实测数值和原文件均保留。

独审第一次诊断session9177 exit1，因脚本末尾过宽地禁止所有.sqlite，误含合法冻结World文件；
完整计量未输出，不能补记PASS。仅修正诊断排除规则后，第二次session16777完成完整对照并保留两次attempt。
未修改生产代码、旧正式实例或实际闭包，未把诊断脚本问题记作模型/组件失败。

同次独审旧语义遍历4.69561秒，新语义11.18316秒＋mandatory close1.51787秒。
运行非独占，且检查时序/收口不同，不能声称通用加速比；更不能宣称R2已比旧Batch快。
当前只关闭R1的指数重复和set子类漏洞。完整Batch中显式合并同次准入的重复检查、
保持各HTTP/事件/父gate的新鲜边界以及实际阶段耗时，仍须实现后单独证明。

## 历史清单与尚未完成

57账精确清单已由`/root/p0_audit`独立核验并保存`independent-history-inventory.json`，
SHA256 `58b388f1370093867bcdeac88ee48f24cf55c6d4e992a7c7561ae27fb471f013`。
主代理再次重算73稳定依赖hash、57唯一有序路径及清单映射一致（chunk d4e9a3）。
legacy两账含3请求／2221已知raw；后55份v2账含55请求／1079208已知raw，全部结算。
合计58请求／1081429已知raw，唯一旧未知28284完整对象保留，总实际仍null。
四旧协调器停止状态、事件镜像和全部未运行位置独审一致；不重复计入中央账，第13FAIL费用未漏。
该清单本身不是运行时历史策略或新授权。其后新增
[历史账适配器](V0222_SCOPED_HISTORY_IMPLEMENTATION_20260912.md)，从同一核验bytes重算状态机，
实际57账已核验；新版Batch仍须接入历史策略、独立核对旧协调器动态终态和完整lineage。

上述R2全仓回归已通过；后续history回归、新Batch动态SQL/期限/事件接线、冷worker与父finish/gate的完整
实际规模时间证明均不能用这些局部结果替代。没有新的正式实例或HTTP准入；旧P3停止、未运行矩阵与
P4/E1/E2/M0/M1依赖不变。整体Goal保持执行中。
