# V0222：显式 Batch 核心接线进度

日期：2026-09-12。状态：`PARTIAL_CORE_IMPLEMENTATION / COMPLETE_BATCH_NOT_READY`。
依据原[V2设计](V0222_SCOPED_ADMISSION_V2_DESIGN_OFFLINE_20260912.md)；旧presentation源码、测试、
正式实例与全部停止证据保持不变。这里没有重新分配模型次数或放宽原16＋条件24矩阵、时间限制。

## 历史与动态终态接线

新增[lineage模块](../tools/v0222_presentation_lineage_v2.py)把57账、静态完整依赖和四旧协调器接起来。
`read_inventory(scope)`仅读取固定清单，不是gate；`verify_lineage(scope)`必须完整核验并成功close后使用。
四库分别开启新鲜mode=ro/BEGIN快照，核对binding、停止状态、完整episode矩阵、launch、中央事件及地方镜像。
SQL不进入固定hash缓存；同一scope再次调用也重新读SQL。四个快照不等于跨库原子事务。

旧清单缺少完整launch信息，独立新增`independent-history-launch-review.json`，SHA
`9c56c0d349b84c08764fae7efbbfc4c1d2a94858ff0ba6f0e1c3def2e32e9b43`；主代理重核35稳定依赖通过。
四库schema对照冻结源码：最旧V0221仅meta/episodes/events、没有launches表，其余有完整launch rows。
最旧live-launch marker没有找到先前hash锚；新审查只固定当前观察，原启动PID/time历史真实性仍UNKNOWN，
不能把新hash倒推成历史不变性已证明。其余三库launch由既有冻结review/marker重建，旧stop/unrun保持。

R1对两个重叠根分别verify_tree，实测20.379秒／259821重复引用，60局部测试通过。
保留R1单文件源码和原观测，不覆盖。R2追加固定`lineage-evidence-index.json`（SHA
`50260be836884ed6b507c77f31e58398f4bc2a94c72338dc435f93d4c486b993`），恰好绑定两个原根；
同一次tree的私有completed消除同用途重复遍历，之后各根语义、history及SQL仍分别执行，不跨操作缓存。

R2有74局部测试及独立同版复跑通过。一次实际完整lineage只读观测12.980秒：5873文件，
首次及收口各344100625bytes，5275JSON，130707重复引用；57账仍58请求1081429known，唯一预约28284，总实际null。
两次各单次观测不是受控性能基准，更不是完整worker/父gate/1800秒阶段证明。
R2观测SHA `9f2677e0fe6ed7e5769dcf07dabd6c6831989dc455a92ae071cf25ee9139ff4b`。

## 新 Batch 已实现的核心

[Batch V2](../tools/v0222_presentation_batch_v2.py)仅复用原transaction/events/stop/snapshot原语，
不继承旧admit/authorize。新增固定候选路径常量`evidence/v0222-presentation-scoped/20260912-http-r1`，
尚未创建该正式目录、授权实例或scope review。模型revision仍INTENT_BOUNDARY_RUNTIME_V1，
协调器另记SCOPED_ADMISSION_V2；B1/D11、来源/动作/顺序、16P3＋24P4、raw cap null均保持。

已接constructor控制校验、显式_authorize/plan、initialize、launch、claim、admit/http_admit、
reserve_request、dispatch_started、settle_event，以及当前journal/artifact读取和P4前置gate检查。
每次_operation独立scope：授权/固定依赖共享bytes，动态SQL/地方账重读；close后再次核查授权、阶段和episode期限，
事务提交/解锁后才返回。模块本身不发HTTP；未来Transport还必须保存attempt/request后调用fresh admission。

新增claims表及原始claim marker，绑定pid/start/派生deadline，检查300秒与阶段/授权共同界限。
停止和期限失败在scope与SQL事务退出后再stop，保留首因。claim收口已超期则SQL回滚，失败marker保留。
reserve与dispatch需要运行准入；settle只允许精确owned旧请求的响应/费用FSM，即使FAIL/过期也不丢弃可信用量。
超额usage先计实际费、同一事务记BOUND_VIOLATION并停批；不恢复FAIL、不能借settle新建预约/dispatch，
也不允许UNKNOWN自动转KNOWN。原文usage提取与来源验证仍是尚待接线的Transport责任。

当前中央与地方事件逐账FSM/归属和全局镜像核验，episode/stage次数重算；未完成episode ledger与中央SQL/WAL/SHM
不能借artifact依赖进入固定scope。成功episode的已冻结证据与当前动态账读取责任仍分开。

## 局部证据与明确缺口

37项动态测试真实使用scope与隔离SQLite，但静态_authorize被显式合成夹具替换、PID/clock为模拟值。
另22项控制测试真实使用constructor/_authorize/manifest/plan校验，仅lineage替换为固定合成清单读取。
组合59PASS（4.77秒），Ruff通过。初次控制测试1失败是测试错误限定异常类别，实际Python漂移已被拒；
按既有ScopedEvidenceError类型修正断言，未放宽生产检查。Python漂移有本组覆盖，包漂移由此前adapter测试覆盖。

P4 initial hash目前只核对64hex与旧值不复用，没有在此重算World派生hash；该义务保留给resolved-spec/reference审计。
这些合成测试没有将两个真实层合成完整正式实例，也没有证明真实冷进程、父子所有权或阶段耗时。
缺少freeze_artifact、独立finish/p3_gate、references公共接线、新prepare/preflight/Provider/Transport/worker/runner，
以及完整16→条件24 Mock和实际规模零HTTP冷执行。不能把当前部分核心叫作完整Batch通过。

源码SHA `c882f8b39202c32928f4d67ccbf30b1f47af120fe1e094365ff3f37f4f8dddc2`；
动态测试SHA `170035c9e778afde97a2d07e8189d48bb01160d38e209e6203750871d6e16541`；
控制测试SHA `cb54908cd503ceec3feadc21d1ec4079eae3c4deb9954f3c355a07940bf77ed1`。
lineage R2源码SHA `3652be5e1ad81c9c30c3e6dcd5df8fb60f15a8de463f246fc72eef5f3b7f482e`；
测试SHA `a774eac377f1525b72d3ce9e73da409df10710358fa2418863aae4fe6624324f`。

此前history全仓50243已2574PASS／1skip（1217.35秒，501e90），不覆盖本页新增代码；
其工程制品SHA `f9e090200eadfe891c2941bfe5329ed79e914cfb5d27f5373b36dc0e158b1ea3`。
本次全仓pytest session67000正在运行，尚无终态；上述11份组件源码/测试保持稳定。
boundary/Ruff/Mypy39源已通过（45aec9），build已通过（51929 terminal44c300）。

限定独审已完成：`independent-scoped-batch-core-review.json` SHA
`f02bd8bf5803dcd3530a9acf2eab2d5ede9fdc96dab1cd765498c958a26b6a0a`（59独立测试PASS），
`independent-presentation-lineage-r2-review.json` SHA
`659d8fd92ff1f8356cf9a1e29bbfdfc5794111722c138a73c0e3e60495d8616f`（74独立测试PASS）。
主代理分别重核9／14直接依赖hash通过（077a56）；没有完整Batch或实际阶段准入结论。
lineage的schema检查是表名集合＋PRAGMA列定义，不宣称已审计所有额外view/index/trigger或CREATE SQL字节。
当前全仓已收集2708项，最终结果仍待原进程；没有创建拟定正式root（077a56）。

后续必须补完上述接线和真实规模验证，再做具体冻结范围审查；不重开旧停止批，不抵扣旧12PASS，
不扩大时间/次数或开放保护池。没有新HTTP、GPU/设备/容器调用、凭据读取或Product/Memory修改。
旧3P3＋24P4未运行状态保持，E1/E2/M0/M1仍按原门依赖推进，整体Goal继续执行。

## P4 初始化接线缺陷与独立复现（追加）

独立审查发现当前core的`episodes/<id>/claim.json`会提前创建原Session要求新建的目录。
`scoped-claim-session-integration-finding.json` SHA
`c230593571741680c96d59070b7ad093e913402f12740bac2eca5c07d4eeaa1f`保留源码定位及验收适配义务；
这不把此前限定59项核心测试改成完整P4接线PASS。

新增[Session衔接回归](../tests/unit/test_v0222_scoped_claim_session.py)使用真实隔离SQLite、核心claim/admit及原Session/World，
仅授权/阶段就绪/PID/时钟为显式合成夹具。旧版真实复现`Session:162 FileExistsError`：
session91310 exit1（cd9e94），1 failed，2.15秒；先前86705只在目录断言失败，未执行到Session，二者分开记录。
复现证据为外部`scoped-claim-session-r1-reproduction.json`；旧core与动态测试各保留一份同hash源码，非活动导入。

修订方向是将claim证据移到`root/claims/<id>.json`，不放宽Session、不删除失败证据。
外部claim/launch/exit不会由原episode递归审计自动绑定，新版父验收须显式校验并纳入依赖。
此记录时67000仍在运行，原11被测文件未改；新增回归不在该次收集内。新版制品冻结与父验收正在离线实现，
尚未完成完整Batch、冷执行和实际阶段时间证明，没有新HTTP或硬件操作。

## R1 全仓终态与目录修订（追加）

原session67000已terminal0（f1c501）：2707 passed／1 optional Host SDK skip，1233.87秒。
退出后11份被测文件hash仍与开跑一致（5ad50f）；外部`scoped-batch-core-r1-engineering-checks.json`
SHA `e594199184db2405c3da9f9733cd9b43230b3500a3f31c8168b3a4c52c3c44c5`保存该基线。
它不包含随后新增的Session回归、制品冻结、terminal适配和父finish/gate。

随后仅修新版core：`claim_marker_path`复用纯ID/计划检查，返回`root/claims/<id>.json`；
claim和动态marker检查统一使用它。旧Session、World、审计器、正式root及原claim失败证据不改。
新版核心源码SHA `193be62755ef444eeaf3e6ec713a1d4a3e5b35afbc4c3e0db34f0bffe45faf18`；
动态测试SHA `8878dabb1d4a489d238f928c19fb07844424bca88d7ed4f18374d8366056651a`；
新增11项Session测试SHA `db79143cca6c467824717f5d436abeb84f4ef7638d16b450a63dab8c8f890704`。
主代理70PASS（72373／0edf4f，7.66秒），独立70PASS（6.44秒）；
独审`independent-scoped-claim-session-r2-review.json` SHA
`8b9fe4bb71f390f8f4cc788d2d2d67d3d4c31f85900cd26a4aba9353b77b2c0a`。
真实原Session初始化/六项公开预读通过，旧目录和缺失/篡改claim负控保持；仍不是P4准入或真实冷进程证明。

初版[制品gate](../tools/v0222_presentation_gates_v2.py)、[terminal审计适配](../tools/v0222_presentation_terminal_v2.py)、
[父finish/P3gate](../tools/v0222_presentation_finish_v2.py)已经落地，初次组合227PASS（86097／eb246b，31.97秒）：
核心70＋制品44＋terminal87＋父编排26。terminal87含4项真实旧audit/Provider/Session Mock，
父编排26的`_audit`明确为合成夹具，不能合并成完整新Transport/Provider/父审计接线证明。
独审已提出制品scope-review实例绑定、P4参考World/turn读集闭包及完整prepared登记缺口，正在修订；
227仅是该初版局部观察，不覆盖修订、不签发完整Batch或真实请求权限。

后续追加：[新版执行接线记录](V0222_SCOPED_EXECUTION_WIRING_20260912.md)现包含 claim 修订、Gates R3、
terminal/父 finish、HTTP/Transport、Provider、worker、runner；当前组合 396 passed（73.00 秒）。
其中 runner 的 gate＋stop 双失败误报 PASS 已独立复现并关闭。新 prepare 另有 11 项局部通过，
preflight 与完整新版 Mock 接线继续实施；尚无实际冷阶段时间、完整新实例或新真实请求准入。
