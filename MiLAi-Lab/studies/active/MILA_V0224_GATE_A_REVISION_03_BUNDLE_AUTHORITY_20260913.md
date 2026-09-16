---
revision: V0224_GATE_A_EXECUTION_R03_BUNDLE_AUTHORITY
status: DESIGN_FOR_INDEPENDENT_REVIEW_NOT_EXECUTION_AUTHORIZATION
date: 2026-09-13
---

# V0224 R03：历史静态证据包 authority 与新鲜动态准入

本文是新工作点的具体设计，不是实现、封存、测量或 Gate A PASS。用户授权完整 Goal 与代理审查；主代理已选择本文的设计范围，仍须另一代理独立审查、具体实现与负控、实际库存以及外部冻结合同，才可执行。代理决定不称为人类审阅。原 V0223 v0.1、R02、K2、current、diagnostic 合同、源码、失败和成本全部保持原样。

依据[诊断到bundle工作点反思](../../docs/V0224_DIAGNOSTIC_TO_BUNDLE_REFLECTION_20260913.md)，诊断独立审查已通过，摘要为 `6671ffd9344006dcdf0005f10a25d2ff68442abe5b35100608e7f679d74a4d17`。三次 S 的前两次 runtime 准入并集约 24.65–24.79 秒，超过 18 秒。完整成功参考 Session 的 7/9 次准入尚未测量。私有解析、资格扫描和 copy guard 已被分开观察；剩余 inventory 仍不是已测的纯路径成本。本文不以两个 guard 的时间乘算未执行链，也不声称新模型必能达标。

## 1. 有意改变的保证

R03 将**明确分类的历史纯静态闭包**从旧离散路径切换到外部冻结的、内容寻址的原字节 bundle authority。封存时完整验证静态语义；每次准入开始和关闭仍完整新鲜读取并计算整包摘要。运行时不再逐项重做这部分历史闭包的 JSON 解析、manifest/引用遍历和静态语义验证。

这是一种经明确授权的跨准入语义验证复用，不是原 R02 的等价优化。旧静态路径在封存后被删除、改名或改字节，而 authority、实际执行文件及所有动态来源未变时，R03 可以继续接受；R02 原本会拒绝。这项逐个旧静态路径漂移拒绝保证被撤销，必须在结果中列为有意差异。旧路径仍保留作历史证据与独立溯源，但不再是这部分运行时 authority。

因此即使未来完成 R03 全门，只可声明 `Gate A under V0224_GATE_A_EXECUTION_R03_BUNDLE_AUTHORITY`。不能改写“原 V0223/R02 全部保证已经恢复”，不能续填旧失败实例为 PASS。若未来 Memory Gate 使用 R03，必须显式绑定 R03 与本差异，不能沿用旧授权叙述。

## 2. 四类明确清单，动态优先

分类由封存审查产生精确路径/摘要清单，不按文件扩展名、文件大小、文件名猜测或“看起来已结束”自动分类。所有原输入必须落入清单并有去向；多用途文件按更严格的新鲜路径处理，不能因它也被历史 manifest 引用而降为静态。

| 类别 | 权威与每次准入行为 | 不允许的替代 |
| --- | --- | --- |
| S：历史纯静态闭包 | 包含历史报告、不可变原始 World 证据、旧执行源码副本、历史 manifest/索引/审查证明等已逐项确认的字节；原路径、摘要、长度、引用来源随包保存。每 admission 整包 first read/hash 与 close read/hash | 不能删减闭包、抽样、只 hash index、不读 payload，或只 cold init 验证一次 |
| L：57 个历史 local ledger | 仍在原路径按原固定摘要读取、严格 JSONL 解析/账务检查，每个新的 admission scope 都 first read/hash 与 close read/hash；保留两份 legacy debt 及另外55份 ledger 的原规则 | 不把 ledger 放进包后取消原路径检查；不把旧 unknown/预留上界记为实际结算；不从 CPU 结果推断迟到用量 |
| H：4 个历史 central coordinator 与 launch 状态 | 每次 lineage 调用都重新打开四个 `batch.sqlite` 的只读事务快照；重新核对 schema/meta/episodes/events/launches 与 local mirror；每次重新 glob 完整 launch marker 集合并读取/关闭复验 marker；四个历史root的 terminal execution-binding/result共8个控制文件仍first/close新鲜检查 | 不是57个 SQL 数据库；不 hash/cache coordinator SQLite 或 WAL/SHM 代替 SQL 语义；不把四个独立快照称为分布式原子事务 |
| C：当前实例及实际执行边界 | 当前 binding/auth/source grant、期限、stop、owner、head/CAS、claims、当前账本和镜像、operation/receipt、当前SQL引用的全部artifact及其依赖并集、父 finish/gate、实际执行源码及执行副本、运行环境继续新鲜验证 | 不共享当前 PASS、权限、预算、读 scope、事务或当前 World/ledger 快照；不因源码出现在 S 包中而免检实际执行文件 |

强制fresh角色优先于bundle membership：即使同一路径已有包成员，也必须走实际来源。角色来自冻结的明确控制面清单，以及原current SQL检查产生的artifact/依赖并集，不能靠后缀或目录猜测。若某历史engineering文件被当前SQL引用，它在本次scope就是fresh文件。若它此前在同一scope曾按静态成员供给，提升fresh角色必须真正重新读取磁盘并登记关闭复验，不能把已有包内缓存计作新鲜读取。提升只能增加检查，不能降回STATIC。

L/H/C 可以在原历史清单中有静态描述或旧摘要，但其运行时 authority 仍是原路径或实际 SQL。包中的描述只提供预期与溯源，不提供“当前值”。如包同时保留它们的历史字节副本，该副本也不得取代实时检查；相同原字节可用同一blob表示，完整路径映射和来源关系仍必须保存。

57 个 local ledger 仍然固定原摘要；任何 append、删改或新迟到事件都触发拒绝。真实结算证据须另行审查并冻结新合同，不能在同一合同内自动更新旧摘要、清债或增加权限。四份 central events 仍只作镜像核验，不再计为四份额外账本。

## 3. 源码中的责任锚点

- [verify_tree / verify_manifest](../../tools/v0222_scoped_evidence.py)：静态完整 JSON、显式引用、原源码/副本、环境约束及失败顺序，是封存语义验证的基线。原模块不改。
- [presentation_history](../../tools/v0222_scoped_history.py)：57 ledger、legacy 未结项、V2 FSM/用量边界及固定总量检查保留在每次准入；不能只读取封存时的 history 结果。
- [verify_lineage](../../tools/v0222_presentation_lineage_v2.py)：拆分静态 `verify_tree` 与仍每次执行的 inventory-purpose、history、launch、四次 `_terminal` 动态责任。
- `_snapshot` 每次 `mode=ro`、`BEGIN` 后读 schema/meta/episodes/events/launches；`_launch_review` 每次完整 glob `live-launch*.json` 并核对 marker 内容；这些调用职责不迁移到 sealing。
- [AdmissionReadScope](../../tools/v0222_admission_read_scope.py)：保留失败 poison、原 first cause、关闭第二次新鲜观察及公共 `read_json` copy-return 安全。两次观察不宣称中间连续不可变，改而复原也不由两次 hash 自动检测。

实际运行环境约束仍来自**全部nested历史manifest**，不只是当前root manifest。封存receipt保存完整manifest清单和每项Python/package要求，独立验证压缩后的等价约束集合：同包名/解释器要求冲突必须拒绝，不能选择一项忽略另一项。每次准入现验全部压缩后的约束，实际当前执行source与executed copies仍fresh first/close检查；不缓存环境PASS。仅历史、未参与当前执行的source/copy旧路径才可转为包authority，并明确撤销那些旧路径的逐次漂移拒绝保证。

将重复manifest环境检查压缩为每次准入的完整约束检查会改变原重复检查的时点/次数；这项差异必须显式列出，不能声称任意准入内部环境突变下与原代码检查顺序完全相同。新接口需固定环境检查位置、双故障优先级及后续动态拒绝责任，不声称连续环境不变。

## 4. 第一版包与外部收据

只实现一种固定、无压缩、无可执行反序列化的包格式，不引入插件式虚拟文件系统。包为 header/index 加顺序 payload，允许按digest对完全相同原字节无损去重，原字节不转码、不重写 JSON。每个原路径映射仍保留，不能因共用blob删除路径/引用。index 至少包含原规范绝对路径、sha256、字节长度、offset、类别与来源引用；不同路径可以共用完全相同digest/length/区间，但拒绝同路径冲突、相同digest对应不同字节、部分重叠/越界区间、非规范路径、未分类路径和额外未引用payload。具体编码、排序、长度上限及总大小在实现审查时冻结。每次必须读取/hash全部唯一blob及有权威性的index/header，而非只校验成员摘要表。物理包字节数与按路径重复计数的逻辑总字节数分别报告，不宣称same IO。

只读现成诊断inventory的布局统计已单列于`/cra/memory/mx_memory/evidence/v0224/20260913-a-bundle-v1/diagnostic-inventory-blob-layout.json`：构造scope7112路径/358665717逻辑bytes，PREP7113路径/358753674逻辑bytes，均对应3195个unique SHA/179702667唯一blob bytes。这仅证明给定库存可以无损去重，不是最终S/L/H/C分类后的包大小或性能预测；7987等合同文件pin数量也不能冒充实际scope路径数量。

封存步骤：

1. 在原新鲜 scope 中完成规定原始闭包验证，保留所有语义错误及原路径首因；同轮执行原 L/H/C 检查形成实际库存，不用旧 PASS 替代。
2. 对 S 路径按本轮观察到的摘要取原字节打包；源文件首读与关闭漂移、打包前后不一致一律失败，不把重读新字节自动封成新预期。
3. 独立读取成包，验证索引每项摘要/长度、完整覆盖和引用关系；从包字节运行静态语义复验，核对与原路径验证一致。独立审查不能仅相信作者生成的 `valid=true`。
4. 输出 receipt：格式/验证器/运行环境版本，完整 S/L/H/C 清单摘要，包与 index 摘要、S entry 数及总原字节数、历史引用覆盖、L/H 清单摘要、原输入来源、检查结果与明确 UNKNOWN。
5. 外部合同绑定该 receipt 的实际文件摘要、包的预期摘要及运行代码/分类版本；独立代理批准后，调用方持有合同摘要。包、receipt 与本地 binding 的相互引用不能构成自授权闭环。

不得在 worker 中重新生成 receipt、重新选择 bundle 或更新 expected hash。任一 pin 漂移必须停止该实例。文件名包含 hash 本身不证明内容正确或文件不可写。

## 5. 最小可执行接口契约

以下为下一步实现的固定接口职责，不是已存在 API。只为 R03 明确调用点服务，不全局替换 reader/JSON/SQL，也不改既有 frozen modules。

- `seal_static_bundle(original_inventory, classification, output_directory)`：执行上节一次封存与原语义验证，返回待独立审查的 receipt；无运行授权能力，不接受调用者提供的 PASS 结果。
- `open_static_authority(live_scope, bundle_path, expected_bundle_sha, expected_receipt_sha)`：在 caller 的本次 scope 中先登记并完整读/hash authority；在本次关闭时强制同包第二次读取/hash/identity 验证。没有 verified bytes 前不能暴露 proof 或语义结果。expected 只能来自冻结合同。
- `authority.proof_json(original_path, expected_entry_sha)`：仅访问已确认 S 清单里的所需原字节；校验 logical path 与 pin，返回严格解析的独立副本，不暴露借用可变对象。它不将旧磁盘路径读一遍再偷偷回退到包；该proof接口未知路径或类别错误直接拒绝。通用scope对未知membership则按原fresh IO处理，两者职责不能混淆。
- `BundleReadScope(AdmissionReadScope)`：显式构造且只用于新R03入口；已封存STATIC成员从本次verified bundle bytes读取；强制fresh角色名单优先；membership未知默认走原fresh IO，不默认为可信静态项。公共read_json仍返回独立副本，原scope poison/close规则适用。不得全局替换原class。
- `verify_tree_r03(scope, root_path, expected_sha)`：仅当receipt明确覆盖该固定root及摘要、分类版本匹配时，以完整bundle authority检查替换静态遍历；其它root走原verify_tree和原fresh读取。不能仅凭某个叶子在包中就跳过未覆盖根的原检查。
- lineage连接：保留原`read_inventory`、`presentation_history`、`_launch_review`、`_terminal`代码与调用职责，显式scope路由只改变S字节来源；57 ledger、历史terminal 8控制文件、launch glob/markers、四份fresh SQL仍执行。所有失败poison同一scope；结果只在关闭成功后可用于后续边界。函数代码未改本身不证明freshness，必须验证其中每次reader路由。
- `R03Batch` 的固定 constructor/authorization 入口：显式接入 authority，保留 C 类 current 检查和原事务/owner/deadline/close责任。R02共享首因修复继续使用并单独标识。原 `Session.run`、dispatch、provider、World/effects 和父 finish/gate 不因本接口改变。

内部如果需要索引元数据可复用，只允许不可变的 `(authority_digest, classification_revision)` 绑定解析结果；每次新鲜包校验通过前不得使用为准入证明。不得复用上一次 admission 的 success、history、current auth 或 SQL。第一可证伪切片无需跨调用索引缓存；是否加入只在实际证据指出必要后单列决定。

实现以固定的新scope adapter连接这些调用点，必须提交constructor、PREP、Session runtime、dispatch前、父finish/gate、commit/收口等所有原admission入口的完整路由表，证明每个L/H/C路径走新鲜实际来源。不能以“命中 archive map”压过动态分类，也不能把 `AdmissionReadScope` 的公共 copy-return 改成共享对象。

## 6. 接受/拒绝矩阵与第一最小切片

第一片只用合成、完整可列举的小闭包：两个静态 manifest、多跳/diamond 引用、一个严格 JSON、一个无关字段含错误 JSON 的反例，再配独立 live ledger 和只读 coordinator 测试对象。它证明 authority 责任和失败语义，不用小片耗时放大预测完整工作点。

必须先证实：

- 相同 S 原字节经原 validator 与 bundle verifier 得到相同静态语义；重复键、非有限值、非法 UTF-8、坏未使用 JSON、manifest 双故障顺序在 sealing 被拒绝。深层结构拒绝的边界说明归属封存验证，不能声称运行时还重复发生同一解析拒绝。
- wrong receipt pin、wrong bundle pin、缺/多/冲突条目、index/payload 变更、替换 inode、关闭时漂移、同 scope 输入异常加关闭异常均拒绝；原 primary 保留，secondary 记载。
- S 原始路径在封存后独自变更而 authority 未变：R03按声明接受，R02拒绝；此项记录为有意差异，不能统计为原/新拒绝等价通过。
- 对 L/H/C 的相同变更仍拒绝：local ledger 改字节/顺序/增加事件、central删除/变化/镜像不一致、4root terminal binding/result变化、glob新增/删除marker、current artifact及其SQL依赖变化、current stop/owner/CAS/receipt/grant期限及实际源码/环境漂移。新scope必须重读；同scope重复lineage调用仍重新做四份SQL快照。静态已读后被current SQL依赖提升fresh的同路径必须额外实际读取并关闭复验。
- 分类清单若把任何 LIVE 路径标为 STATIC，即使包摘要正确也拒绝；关闭失败不恢复资格，不让 source authority授予模型/HTTP/设备权限。
- 公共返回对象修改不污染后续 proof 或关闭；并发、重入、跨 scope 使用及关闭后使用均有明确拒绝规则。

小片通过后才选择一份完整新鲜 R03 fixture：核对 S 原字节覆盖加 L/H/C原路径覆盖等于完整规定负担。报告逻辑 entry/历史引用/账本数量与实际 physical read/hash bytes 两套指标；不能把一个包读取称为仍做了5000余个旧路径fresh open，也不能把更低实际parse计数伪造为原R02计数相等。

新旧差分分两部分：保留的动态/账务/效果保证要求一致；authority转换有意差异逐项匹配本合同。未列明的新差异阻断准入。实际完整比较、受影响计量校准、负控、工程检查及K3所需新roots/顺序/资源由独立冻结子合同规定，本文不授予一次额外试跑。

## 7. 不变资源、完整 Session 与后续门

零模型、零 HTTP、零设备调用、并发1；工程本机协议例外不适用于R03实验。保留原16 P3+80 P4参考、24效果链、16+24实际冷进程、父finish/gate、独立World回读及所有适用A1/A2负控。不得删矩阵或借旧检查结果补当前工程PASS。

完整合法P4参考有 `actions + readback + finish`：single/complex各3turn，double4turn。原 `Session.run` 入口一次、每turn入口一次、每个dispatch前一次，共7/9个runtime PREP准入。当前首generate截断只覆盖前2个，还分别剩5/7个，不能作为完整参考通过。

- 每个完整参考Session内**全部7/9次准入时间并集≤18秒**；从原Session起点到关闭、结果落盘和完整终态≤60秒。不是每turn/每个参考输出18秒，原finish状态本身也不能代替实际60秒终态计量。
- 正式链及归属它的父准入合计≤90秒，完整链≤300秒。
- P3/P4完整CPU阶段分别≤900/3600秒，并保持原1800/7200秒阶段硬期限；含父子准入、调度、finish/gate、报告与退出。
- K3 seal/init≤300秒、完整参考准备≤3600秒。bundle创建、完整静态验证、独立机械复验与相关报告必须记入真实准备成本及所属seal/init生命周期；不能提前移动后宣称这部分成本为零。若拟改变生命周期归属，必须先另行审查，本文不提供例外。
- 所有新计量步骤先冻结明确上限、次数和停止策略；观察扰动必须重新校准，S/U中位≤1.10才能解释分解，不沿用旧比例、不扣探针时间、不重跑取快。

只有新模型下完整资源、动态/语义、效果矩阵和当前工程terminal全部实际通过，才可能声明R03 Gate A。若未达18/90或其它期限，保留失败与未运行项，继续新版本决策或提交明确丢失保证的简化testbed；不回改阈值、旧sources、旧PASS或旧未知费用。

## 8. 本文审批与下一步

新开发与raw证据目录为`/cra/memory/mx_memory/evidence/v0224/20260913-a-bundle-v1`；不向已封diagnostic合同或源码回填本修订。

下一步限于独立代理审阅本范围、固定分类/接口差异及小片实现计划。主代理随后决定具体新文件、测试与执行子合同；本文不触发fixture、性能或完整K3。独立审查记录须绑定本文最终SHA256并保留非人类审阅标识；未来实际freeze再绑定实现及证据。
