---
goal_id: MILA-V02-24
status: IN_PROGRESS
current_gate: GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY
active_scope: NATIVE_WMA_FOUR_ROOTS_RUNNING_B_TO_E_PAUSED
current_model_allocation: 2002
current_http_allocation: 4006
current_note_http_allocation: 1884
memory_status: MEMORY_NOT_ADMITTED
memory_valid_denominator: 0
---

# V0224 执行状态

用户已要求执行完整 A–E，并委托 subagent 代替人工批准、审查和标注；代理审查不是人类审查。技术门和停止条件保留，主目标未完成。

**当前进度：功能 Gate A 已收口；原生 WMA 四根两臂正在真实执行。** 运行与 Judge 已依用户指令冻结，Judge 使用现有 vLLM，4 个评分校准样例通过。范围、区别与上限见 [原生薄适配说明](MILA_V0224_NATIVE_WMA_ADAPTER_20260913.md) 和 [运行 manifest](../../configs/v0224-native-wma.json)。尚无完整配对研究结论。以下 Gate A 及旧 A–E 记录均为保留历史。

**Gate A 终态：功能 Gate A 已通过。** 最新用户收口范围已完成；B–E 暂停，完整 A–E 主目标仍未完成。证书 [functional-gate-a.json](/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1/functional-gate-a.json)，SHA `3d097412d70592454ae13d27352a03b79f526cd47069dda5f4c688c3c86419a8`。以下为按发生顺序保留的历史记录，最新完成回执见文末。

- 历史工作点：Gate A / R02。K2单次55-scope配对独立审查通过；当前候选六进程校准独立通过（S/U中位1.022818806），但两runtime guard并集24.50–24.65秒超过18秒，当前工作点余量失败。实际session28074已退出0，不再进入K3。
- K2实际结果：共享事务首因修复基线753.294781秒；加只读遍历候选670.586224秒；比值0.8902042611，减少10.9796%。两臂各55scopes/54guards/16P3参考，原首P4诊断停止及当前账本语义一致。单次结果，不是统计显著性或Gate A。
- 进程：两child、pair parent及外层均实际退出0；完整外层1427.33秒，旧session4399已结束。所有已计时实例不复用。
- 余量：K2严格U无内部计时，不能推断18秒门。旧K1两runtime guard并集28.868764秒；旧S/U中位1.0265197076只属于旧栈，不能认证当前候选。
- 下一单步：诊断观测资格已独立通过，当前工作点余量失败。制定新R03静态证据包authority合同并独立审查；57历史local ledgers、4历史central SQLite、launch markers、实际执行代码/环境及全部当前动态控制仍逐次fresh验证。新合同明确不等价于R02，不能追认原Gate A。当前全工程与K3完整16+80参考/24效果/40冷进程/父收口仍待完成。
- 历史保留：V0222停止批；K0v1 strict-U拒绝；K0v2冻结及K1校准/55前缀；K2诊断停止。审计脚本r1的变量遮蔽错误单独保留，r2只修局部变量名后审计退出0，未重跑实验。
- B/C/D/E均未触发；模型/HTTP为0，Memory有效分母0。没有Gate A或研究完成声明。

证据入口：

- [K2冻结合同](/cra/memory/mx_memory/evidence/v0224/20260913-a-k2-v1/contract.json)：`d4169589018c3dab07d8dfcf2e45da18d5b873f918fcdeca2fa1db519aad45c0`，6965pins。
- [K2独立结果审查](/cra/memory/mx_memory/evidence/v0224/20260913-a-k2-v1/independent-k2-pair-review.json)：`416d712429f61bceda2113af8b590d21fa1cfd41e71d4c25f63e13bff39d0046`。
- [实际外层工具终态](/cra/memory/mx_memory/evidence/v0224/20260913-a-k2-v1/pair-envelope-tool-terminal.json)。
- [当前校准合同](/cra/memory/mx_memory/evidence/v0224/20260913-a-current-v1/contract.json)，最终独立审查已完成；仅观测资格通过，余量失败。
- [当前观测与K3实施图](/cra/memory/mx_memory/evidence/v0224/20260913-a-k2-v1/candidate-calibration-k3-implementation-map.json)。
- [R02明确语义差异](MILA_V0224_GATE_A_REVISION_02_TRANSACTION_PRIMARY_20260913.md)。
- [K0v2合同](/cra/memory/mx_memory/evidence/v0224/20260913-a-k0-v2/contract.json)、[旧K1校准审查](/cra/memory/mx_memory/evidence/v0224/20260913-a-k0-v2/calibration-review.json)、[旧55前缀成本审计](/cra/memory/mx_memory/evidence/v0224/20260913-a-k0-v2/prefix-cost-audit.json)。

当前反思与下一版本：[工作点反思](../../docs/V0224_CURRENT_WORKPOINT_REFLECTION_20260913.md)。待区分inventory内部纯成本，尚未选择或测量下一性能候选。当前全部工具进程已结束。

新观测修订：[inventory诊断01](MILA_V0224_INVENTORY_DIAGNOSTIC_REVISION_01_20260913.md)。raw `20260913-a-diagnostic-v1`，父15、worker31、探针25项局部测试通过，交叉独立源码审查及24pins复验通过。12步夹具准备/清点与组装均实际退出0，独立冻结及最终7987pins复验完成。正式六位置诊断校准已全部退出0（actualsession31985），合同7c32de70157656bb8b0079db8fb80c5b1f1d9eb48501ca2a9703d95f0499056e。

诊断终态：六位置实际退出0，parent393.440299秒、外层393.53秒；独立审查 `diagnostic-calibration-review.json` SHA6671ffd9344006dcdf0005f10a25d2ff68442abe5b35100608e7f679d74a4d17，S/U中位1.030183429072262。三S前两runtime admission并集24.702871676、24.649474603、24.785842443秒均超过18秒。parse约5.11–5.21秒、eligibility约2.82–2.86秒、copy guard约0.574–0.580秒、其余inventory约8.81–8.89秒；其余不是纯Path成本。完整Session正常路径为7或9次runtime admission，剩余5或7次未测，不作外推。全部实验进程已退出，未运行K3/B–E，模型与HTTP仍0。

R03设计范围已获独立代理批准（rawBundle/independent-r03-design-scope-review.json，b7f75645fc0d748918db594763e9966a3c446adafd90c3f3b93d30a5a728093c），仅合成小闭包实现/局部测试。新BundleReadScope 24项合成测试实际23138退出0，独立源码审查8c6e94bfebf844861c03e6167aee8c4812bac2f35e67b40d6ebb215e513a9d74；封包器、完整分类/Batch路由、真实fixture和计时尚未获技术资格。初轮fixture环境字段失配13fail/6pass记录保留，修testfixture后19PASS，再新增负控24PASS；不作为真实Gate A重试。新反思见[诊断到封装](../../docs/V0224_DIAGNOSTIC_TO_BUNDLE_REFLECTION_20260913.md)，R03见[新authority合同](MILA_V0224_GATE_A_REVISION_03_BUNDLE_AUTHORITY_20260913.md)。

R03完整准备链与单参考worker代码已完成，十模块联合synthetic182PASS（actual47691/8a4225 exit0，14.50秒），Ruff通过；这不是全工程或真实Gate A。root独立准备/worker源码审查0d706b091696c58c2b1dcb507f0cb4a299bfc6587c520193089405f5c753abf0；finalizer独立审查eff4f2c52018b0303cf9b950b99b04843b0862b435d685fd3435a2c04a6ff9d0。具体准备合同for-review SHA7c631bb4b22b627505b928506e10237d28c406a2082831dbfd16b58b5acb5ca5：6静态roots，7113继承路径，180执行源码，252mandatoryfresh（72历史+180源码），21允许新增源码，202外部pins。独立冻结审查中；真实封包/夹具/完整参考尚未运行。准备controller的单300秒包括审批等待、authoritybuilder/finalizer/fixture三child及报告，310外层仅清理保底。

当前R03准备：v1封包与独立机械复验完成，但外层timeout默认后台进程组使批准stdin读取暂停；actual67692/915211退出143，285.99秒，finalizer/fixture未启动，失败保留。经实际foreground stdin probe退出0与独立修订批准27921a5dacad879de2ff4f4fd6284fc7c5d8023bbc2267a236264322a1ab732a，v2在新raw `20260913-a-bundle-v2` 从封包重新开始，代码/合同SHA不变，外层仅增加`--foreground`。当前actual87116运行中；新builder2995926实际退出0/46.295232秒，等待新实际包审批，全部300秒仍包含等待。没有真实fixture/reference/K3或B–E成绩。

R03 v2准备实际完成：87116/659386 exit0，完整外层133.96秒（保守上界133.97≤300），builder46.295232秒/finalizer1.617078秒/fixture15.041467秒，审批等待70.498884秒包含在总耗时内。全部子group与父进程已消失，202外部pins重核。新fixture为`20260913-gate-a-bundle-v1/bundle-v1-slice`，binding c9a5ded1ade27889bc0742a25d32d1338f1f1d56d83854f3e9ec429c3f7bec84；approved receipt 7fe89df50be05d4a8f376582a748463abc5d9380e6fd43ba3fdf9af0794a33ee。真实reference尚未执行；下一单步是独立fixture准备完成审查→冻结六表baseline与首P4合同→独立worker准入。

R03准备完成但reference准入前发现接口缺口：独立readiness审查32ad1cdfedf638478c15dc356597f8183cefb79d797b43fbbcb2b5bd392de77f为REVISION_REQUIRED；24个P4 resolved值全部正确，4个public-initial已在历史认证闭包内，但当前manifest.inputs缺少worker/assembler要求的直接pin。具体记录514d885c5c20ab5fb18fb7cb9f8e028dc72a37d6d81f3a9a962bf00c3a16385c。未运行reference，不补改旧manifest/180sealed源码。新development位于raw-v3，拟bundle-v2-slice固定新root，versioned Batch/fixture/worker/controller；fixture将4已认证publicpins直接纳inputs并保留原expected，完整7113继承与旧源码负担保持。旧包/实例/成本保留，不把旧bundle容器递归加入新运行闭包。下一步局部集成反例→独立新源/范围/具体准备合同审查。

来源绑定v2代码与接口55联合测试实际90487/5029dc退出0（10.95秒），Ruff通过；root独立源码审查62bb6430370e692b9420b36b12f72cb77a48424da918b3308f9736652c2f744f，raw脚本独立审查3d0a835b2937dbc1cba33ff34b19e9326ef528f4639d80f72c0bba55486597a4。新具体准备合同raw-v3/for-review bde928f9f534f11b17056bf5042a2718b7ac6869f4669ae0a14130a4703bbce7已组装（38296/555fd4 exit0），6roots/7113继承/186源码/262mandatoryfresh（含4currentpublic）/27extras/219external，独立冻结审查中。新真实包/夹具/reference尚未运行。

新来源绑定v2准备实际完成：54512/264a30 exit0，完整150.62秒（保守150.63≤300），3children与父终态0且全gone，219pins复验一致。root只读确认当前manifest有4个原public directpins，16P3+24P4全PENDING，claims/events/launches均0。binding fe142691c40b5812955ae5ae3003992516a212d5ac3f90a42506dd05897fdf04；newbundle93e4b6430f52e5275d4856f4bba9a9e118b0d0d2d85289f3325408cc8f5a55dc、receipt4136739a8833d414540bca2b7e69f160f80768ffda4edb8a4e9304f48cbb8a87。独立readiness审查中，真实reference仍未执行。

首个完整P4 reference实际执行并结束：冻结合同9bb379120d94d5aa4fdfb35d02268e1ea3328a59eb62fbd68edbed729dbed830，独立执行批准1c8129176d55a208ff711c058af2dd5f99a0d86dd068d4fbe4698dfef864af1e；actual65699/0d6efc exit1，全外层32.53秒。9/9准入callback全部返回（2setup+7runtime），原Session与prepare完整结束，Session19.656887333秒超过所采用强18秒wholewall门，首因STRONG_OUTER_WALL_LIMIT_EXCEEDED_NOT_UNION_FAILURE；准入精确并集尚未测量，不能因此断言其>18。SQLafter和435pinsafter成功，root435input+32rawpins独立复验一致，ownedgroup/parent全gone。原结果raw保留，外部效果审计尚待独立完成，不重跑此实例。后续最小诊断/修订由失败证据决定；全K3/工程/B–E未完成。

当前完整运行时观测修订：旧首参考独立失败后审计44c265a11de8c1fee0d52f00c1d5b4ee18f549b29c439e7d105699898c07001b已完成，原15层参考审计、独立World/effects及六表SQL不变均通过；这不补写旧worker未返回的rows。新raw `20260913-a-runtime-union-v1` 的严格U直接调用原prepare，S只在新Session实例包裹完整validate_runtime（含callback后Host检查），测7个非重叠完整区间；保留原60秒Session期限。固定六位置U1/S1/S2/U2/U3/S3，主观测资格为三组paired S/U比值的中位数≤1.10；ratio of medians只描述。56项联合合成测试实际17999/be8b34 exit0、3.84秒，Ruff d6f62f exit0；helper/workpoint独审e1f2fc4ae370d2085ed01c8a4514563d30e32c7685eb6ca1629bda332e348685、runner独审00a6774e2cd44f39cb7a0ff9dda649c52310b33ea136d06232b0884e6df79b52均通过。当前无真实准备或校准进程；下一步具体合同独立冻结→新authority及六夹具共用300秒准备→六位置共用600秒校准。完整K3、当前全工程和B–E均未完成，Memory分母0。

完整运行时校准的新准备已实际完成：准备合同1208476f0110fedd9432aea01bfe3152c96d608022604ff9c41ad1958c4a8c4e，独立冻结a7a9d826579c63a0a5f0ce6f37d9da3b9b473cf93140d7943415e05ebcbf5e6e；7113继承/194源码/270mandatoryfresh/35extras/239external。actual38034/5adce7 exit0，外层199.63秒（保守199.64≤300），builder46.958秒、独立完整package replay实际95574/45479a exit0、新approval4caa127c1c00a1d8cae5390d1d1c5b32d138abc0e1da2b13b9c83b488edd1ccc及六夹具均在共同预算内完成。root终态审计4b6a0c exit0，八children/父全部gone且239pins不变，terminal SHA c475f00790d92ae6a7e5758e094c5d8c2fd6c071bbf49c134e5526ab8e456209。六夹具独立readiness审查中，真实校准仍未执行。

完整运行时六位置校准已实际完成：readiness独审7d5dae8b1f79ca02b2af1953b12f34e6c2ede3537ad882ec730a7f23ac50e60f；2725输入校准合同17250e31c6e08e6ac48ac3591c5a1c145008478ae13fe86c57eb90fffa9a9c6e及独立执行冻结9d4f821e30acc180395439cdc2dbd44a0df5417790df371819a2d8f77fb6162a。actual92840/f24910 exit0，六child全0，完整外层保守202.64≤600秒；root终态复核38680/cb2930 exit0，terminal e5b04ebe7288f26959f3834148edf25b010381894b6a0c89273f6358827eebe1。三U完整child33.467901400/33.472009624/33.218158425秒，均≤60；三paired S/U中位1.000074425967013≤1.10，观测资格通过。三S完整7次validate_runtime并集18.483173292/18.448296345/18.298297905秒，逐项均超过18，当前余量门失败，不能进入K3。全六原raw效果/SQL/计量独审中；下一步基于证据选择一般性最小性能修订，旧六位置不重跑、不改判据。

独立全六runtime审计b453e5f2a913c1c621262c776dcd83fd305c63e0b4b68f8b8c0f8c9843710765确认语义/效果/SQL/计量有效，18秒余量失败。后续原parse诊断actual80502/e10f08 exit0，三原完整调用0.869288938/0.861378665/0.862589531秒，独审9cacf38a45fa2a359912c20d6c4bd5ac110b8686b9e68412b9877b032de33143通过。新split合同d6a27af67ac92141c352e9bf35eea42db9f44c5bc65066454b63fc190dc6e4df、独立freeze3c7ec15b14592478b6c547ad1987728eb4cd59dba6342b120e2a66f771f1a985；actual77828/5f557a exit0，完整外层保守6.75秒，一进程同buffer U/S/S/U/U/S六API调用paired中位0.996397314781101，probe观测合格，不能代替Session校准。S header63.0–69.7ms、blob布局/hash约398ms、tail约395ms（其中wholehash约392–393ms、tailexclusive约3.2–3.4ms）；无双计，split独立结果审计中。成本证据优先指向同scope同immutablebuffer重复wholehash，暂不选择跨scope元数据缓存；下一最小候选仅设计，需保留first/close两次freshwholehash、每blobhash、完整metadata及动态检查，显式新合同后才实施。

R04唯一性能候选已完成有限开发及交叉源码独审：[同scope摘要复用规范](MILA_V0224_GATE_A_REVISION_04_SCOPE_DIGEST_REUSE_20260913.md)，doc SHA4ef7add0129fa6686a4c96396d5bb9bf8176e82647e32b108db463a9af6537da。原first/close实际wholehash与全blob/hash/metadata/dynamic顺序保留，仅私有scope-bound parser末端重复wholehash替换为当前_entry已经验证的expected，无裸raw/digest入口和跨scope缓存。core独审80e412825fbb59f8128c3922e56fd6c827226250db459fae12f666e80c9053e3与patch范围澄清6588236e870f4ca65a87f40d8779a9dba54ededb8215a5c4d508d937dc264036、工作点独审56bb3685acedd35f3b70bb1732f9d30d65cf3453c1dd2aae30f9b16677a78173通过。87joint synthetic实际23253/c02650 exit0（3.84秒），最终Ruff0a8826 exit0；synthetic fakeBatch不等于真实R04 Scope+Session。新raw `20260913-a-scope-digest-v1`，固定新六root `digestv1-d1-u1/s1/s2/u2/u3/s3`；实际合同/authority/fixture/calibration均未运行，准备脚本独审中。


R04 准备实例 raw scope-digest-v1 已结束：实际 session 81643 / start 8321fa / terminal 14d59b / exit 1；仅 authority builder 成功（47.1905014878 秒），随后独立审批等待耗尽完整 300 秒，外层 300.35 秒。交接期间未及时触发审查，不是算法性能结果。root 独立失败收口 24f0bd exit 0，父、timeout 与 builder 进程及子组均消失，262 外部输入 pin 无变化。失败凭证 preparation-failure-external-terminal.json SHA256 30e4b2c605f1adf4b32db6aa2750e7fa5cfd66690c4917b765cb1d577abfe464。无 finalizer、无六夹具、无 reference；旧实例不续跑。新 raw-only 实例方案独审中，300 秒不放宽，实际 launch 前先确认审查 agent 正在等待。A–E 与当前工程仍未完成，HTTP/model/device 0，Memory 分母 0。


R04 raw scope-digest-v2 准备完整成功：合同 2fddf7e2be0c846e31e65650c91db52d9008d42ab3520347b51e04a89dcdac30；actual 78223 / e6e813 → 98920c exit 0，完整外层保守 214.74 秒。新包独审实际 66347 / c26de5 → 04cc10 exit 0，审批 4ecc5b840957a08b91740b2c961e5f0ed1be3e04ff239f7c76cd63b8b5699f52。root terminal 审计 97015b exit 0，8 children 全部成功并清理，271 输入 pin 未变，凭证 SHA 5178dda70bcee4fc972b4d527896ea6b61231ba79eac63288e91fdc3d9a00cd6。保留原6个此前未创建的固定 fixture 名称与9个已封源码；旧 raw-v1 失败不改。六夹具独立 readiness 审查进行中，计时校准尚未启动；不代表18/60、K3 或 Gate A 通过。


2026-09-13 v0.3恢复执行：A0独立完整收口通过 R04_SEVEN_RUNTIME_CALIBRATION_ACCEPTED；报告 raw scope-digest-v2/independent-r04-a0-calibration-review.json SHA256 5ba177bd85576f92e8d5eaf3f7047353257c268d46a950d162afb4ef4c034a3a，blocking_findings=[]。核验实际18rows/90layers、六World/effects/SQL、2813输入与raw首尾、179.63秒完整校准；三组runtime并集15.775482363/15.725068708/15.764869123秒、paired median1.0048351789385712。57ledger/四历史SQL/环境另作事后只读补验，不倒填原计时；动态负控区分当前scope与历史synthetic适用性。未重跑六位置。下一步 A1：原manifest index2双对象两动作/四轮/九runtime，原complex仅一动作，形状选择记录SHA792d2f5600097e378e38f3817e7e0fca98499c502d2e4fbf377c1ce1713c6631。A1开发与新实例冻结待完成；完整A2/K3和工程、B–E未完成，Memory分母0。


A1完整结果（2026-09-13）：准备 actual27289/93e4ef→37c5c5 exit0，保守230.79秒；209源码/原203逐项保留、285fresh路径。四轮六位置 actual85095/7936a2→5a3ad9 exit0，完整外层213.33秒；root外审80398/6638a9→dc0d0a exit0，terminal SHA5c4bdb7151f60df5422a610172dec6380eac029887e2476633c7b014f1fee790。独立结果 SHA44dc8703222bd52dcbc000708a35c6a2329b59e9caa7bd7585ae56aa42b1395d，A1_NINE_RUNTIME_CALIBRATION_QUALIFIED_HEADROOM_FAILED：24rows/120layers、六组两动作World/effects/SQL、2867inputs与42raw/worker首尾有效，paired median1.003934603331897；三S九段并集20.208416342/20.984938971/20.303233425秒，均超过18。A1失败保留，不启动K3；后续仅一次固定zlib level1表示可行性检查待源码/合同独审，不修改runtime或逐scope保证。A0局部验收保留，完整A2/工程/B–E未完成，Memory分母0。


固定zlib level1可行性探针已收口：合同26b9dc66776bfb3aa4323f760567f9ce441412bf924fd7c41dad809471701c0e；actual53976/a5915f→e39229 exit0，完整保守7.94秒。包180795404→40748583bytes，ratio0.22538506012022297；encode3.832900367、decode1.491189601、原完整parse0.863920275秒。root审计3fadb5exit0，独立结果7d1f3d4ef0f4295e782b7f1935808dd3f0b4b40c401cbfaa870d9162cbff7bc3。未测完整transaction改善；不实施压缩候选、不换codec复测。内置zlib组装兼容错误与修订已保留，真实探针只运行一次。下一步是v0.3 §4允许的显式简化测试床合同草案：cold worker一次完整验证static immutable bytes、之后全部动态边界仍fresh；若采纳须列明失去逐准入static路径首尾/逐blob重验保证并使用新证书名，不能改写旧R03/R04或A1失败。A2/K3、工程与B–E仍未完成，Memory分母0。


用户最新要求完成任务优先，停止严格CPU效率优化。依[优先级修订](MILA_V0224_COMPLETION_PRIORITY_DELTA_20260913.md)，取消未执行的R05准备与后续效率校准。原R04 A1正确性证据继续有效，旧18秒失败保持历史事实；18/90及阶段CPU效率不再阻断。直接实施完整K3与后续B–E，仍保留正确性、隔离、真实账务和科学矩阵。当前Gate A功能验收、B–E尚未完成。

## 完成优先：K3实际准备完成，完整reference运行中

新单K3准备实际父工具73437/f044a4退出0，228.16秒；builder/finalizer/fixture三个子进程均退出0并清理。最终Batch修复遗漏的claim阶段期限，47项相关合成检查通过；保持原R03/R04每次fresh校验，无R05运行。K3实际合同SHA `e9741312450a9634624a787a67a037c4235d20ca6042d7131478013d6fbae33d`，1713外部pin、217源码、完整40位置。reference已以工具61300启动，尚未宣布通过；当前工程全量pytest仍运行。独立包核对初次误用系统Python的失败保留，改回builder同一Lab虚拟环境后完整原parse/verify_tree复验通过。后续B/C新源码仅前瞻开发，真实HTTP和模型请求仍0。

最新进展：完整16+80 reference已实际61300/a0b36c退出0，818.24秒，独立scope review通过；P3预检58041/9ede5d退出0，163.11秒。K3 P3完整16/16及父收口实际63686/49c03c退出0，1500.34秒；父PID54906已消失，终态 `P3-external-terminal.json` SHA `786f86dc6293c8623272fc2aa4aee39f80243afa0df9da15bc6dc877e95d2dcf`。P4完整80行预检已启动55417/f9fc02，PID143251已实际观察；随后执行24冷链。CPU效率不阻断，工程全量仍在原进程继续。B/C、D1/D2接线仅源码与合成验证；D自然结果与执行完成分离，未真实调用模型。Gate A及A–E仍未完成。

P4预检已实际55417/8e9623退出0，834.60秒，完整80行/160 mock tokenize，终态SHA `5c4e84dae9cbb0bf234cc37d27ab7dd94c341cae344c8a2b56a039feb517fc61`。24冷链24316/2a4c4a运行中，最近只读状态3 PASS/1 RUNNING/20 PENDING，无stop。工程v1全suite实际4245 PASS/1 SKIP/1 FAIL（唯一失败为CLI选择器环境跨测试泄漏），其余五检查退出0；不签工程PASS。新增未进入K3源码闭包的tests/conftest.py仅保存/恢复每个测试原有MILA_V0224_INSTANCE，污染者到受害测试的自然空环境组合已退出0；新engineering-v2工具36538/ffd94d正在完整重跑。K3源码和已冻结test pin未改。

E0已在独立raw目录复制并验证公开源码、离线安装Runtime/MCP及公共init生成自有配置；尚未启动服务、发凭证或发送HTTP。独立产品锁 `20260913-e0-public-completion-v1/product-install.lock.json` SHA `a2b00088717de60444d9d4c21f48e911f25aef8c2b45ff66008c9145c81467c3`，原Product与Lab现有lock未改。公开local OAuth不支持所需细粒度Note只读grant；采用待机械验证的受信Host固定只读来源入口，明确 `HOST_ENFORCED_READ_ONLY_SOURCE`，不冒称Product凭证只读，Product承担真实主体隔离。客户端14项合成已通过，实际公开接口验证仍等功能Gate A。D与持久Note Host源码准备不等于自然模型或记忆研究成绩。


P4 实际终止：24316/2dd7d7 exit1，前8 PASS、第9 FAIL、后15未运行。失败worker已完成4turn及local World结果，但旧300秒外层在退出校验期间将其kill，实际303.081秒/-9，不追认通过。终态SHA10838aed8f4c21a73d10e35ece7ca75f8da5ea48e901d0b238f6ae7d359363a0。按[分段补全修订](MILA_V0224_CPU_COMPLETION_SEGMENT_DELTA_20260913.md)只新冷执行原9–24，不重跑P3/前8/reference、不改旧SQL。原单实例K3审计不再适用于组合证书。工程v2仍继续；新segment源码正在开发/独审，尚未实跑。


用户最新收口范围：当前只完成 Gate A 的 P4 剩余位置、工程终态和一次现有组合验收；暂停 B–E 前瞻开发及实际运行，不增加验证框架或性能候选。原完整 16+80 reference、P3 16 PASS、原 P4 前 8 PASS 继续复用，原第 9 条失败保留。新补全实例 `20260913-cpu-completion-segment-v1/segmentv1-p4` 准备实际 61401/881e8d exit0，合同 SHA `0e283e82fe06b27ffeb084f108c039bf5e88eda43e9b401a4d39bd7914ec8ac8`；stage 工具 22916 已启动，使用 worker 3600 秒、phase 129600 秒完成期限，只执行原 P4 第 9–24 条，尚未取得整个 stage 终态。

工程 v2 已实际终态 36538/99ba4c exit0：pytest 4285 PASS / 1 既有可选依赖 SKIP，boundary、Ruff、mypy、build、diff 全 exit0。最终回执 [engineering-checks.json](/cra/memory/mx_memory/evidence/v0224/20260913-a-completion-priority-v1/engineering-v2/engineering-checks.json)，SHA `de09c27a01ce5f0c86974da699a5c1e97831d38cf1752d6448209d0936984b80`，blocking_findings=[]。旧 217、新 225 执行源码闭包均受覆盖；既有局部验证与全量 collection 范围分别记录，保留 v1 失败。此为工程通过，功能 Gate A 仍待补全 stage 实际成功和现有组合验收。


功能 Gate A 实际收口：补全 P4 第 9–24 条全部 PASS，stage 工具 22916/97594d exit0，4506.64 秒，父 PID406291 已消失；原完整参考 16+80、P3 16/16、原 P4 前 8 条未重跑。组合后 P4 24/24，共 40 个成功冷 worker、41 次真实尝试；原第 9 条超时 FAIL 与旧 SQL 保留，明确不是单批 40 次全部成功。accepted mock generation 96、失败尝试 mock generation 4、合计 100。

既有组合审计仅执行一次：11728/bb6975 exit0，94.02 秒，报告 `independent-composed-k3-completion.json` SHA `6bf19eb4d672201d895d29d7c7f9d655762e6dfbc0e61af8907830ecd54cebf9`。24 个 P4 World 完整重建、原 CAS/回执/效果审计与存储结果一致、账务有效、两份 SQL 首尾相等、全部 worker 和阶段 PID 已结束。工程六项既有 PASS 回执共同进入最终组装。

既有 Gate A 组装器实际 64875/53ab4c exit0，4.53 秒，最终状态 `GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY`，blocking_findings=[]。证书 SHA `3d097412d70592454ae13d27352a03b79f526cd47069dda5f4c688c3c86419a8`，原始组装日志及 `gate-a-assembly-tool-terminal.json` 均保留。18 秒等 CPU 效率指标不阻断，历史效率失败仍保留，未启动性能候选。本次为 Gate A CPU 功能验收；真实模型请求与实验 HTTP 为 0，工程隔离本地协议 HTTP 单列账务，B–E 未继续启动，Memory 有效分母仍为 0。
