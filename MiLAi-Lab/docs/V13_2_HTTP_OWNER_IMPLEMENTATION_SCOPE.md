# v13.2 共享 HTTP 与连续账本所有权的实现范围

仅由既有 `/root/v13_2_source_resume` 在 Root 创建的新隔离树 `v13-2-http-owner-implementation` 执行。精确基准 `8b1fdf3c017477ee80a0284f08ca4a1f5f52e670`，当前运行/测试/完整配置 maps 为 213/391/316。旧 Source 树 READY/HOLD，主树运行源码 HOLD。Root 先发布并核对本范围、创建新树并保存真实创建前后身份，再发送明确启动消息。本文件不授权真实模型/embedding HTTP、读取真实账本/cohort/fixture/rubric/scorer/gold/config 内容、SDK/服务升级或 Product/Archive 改动。

## 通用合同

新因素 `http_ownership_profile` 默认 `legacy`，opt-in `serialized_ledger_owner_v1`；新增 `http_ownership_domain` 为显式冻结的 deployment ID 与允许的完整、规范化 VLLM client 配置集合。不把 Root 真模型名称、服务 URL、真实账本路径、业务值或 case ID 写入运行代码。未知值、非法/缺少 domain、prepare/live/resume 变化及冲突在 ledger/client/SDK 构造和实际派发前拒绝。默认 absent/explicit legacy 不新增冻结字段、wire/prompt/tool/grammar/receipt，也不改变原 legacy 缺失临时预算创建行为；新 profile 的实际账本必须已存在且可信，不能新建0账本。

只实现一个基础设施因素：一个合作进程租约、同一预算对象和所有参与 transport 共用的请求互斥。原检索/选择/排名/2048/max6、Host/writer/业务/存储职责、Source/owner/hash/角色/读时版本、native 算法和原回执语义不变。不开启或改写 generation admission，不把请求串行称12/24共同 inclusive admission、四臂公平性或模型质量验收。

### 进程租约

稳定 sidecar lease 由 canonical ledger 路径决定，所有共享该账本的根/cohort/arm 使用同一路径；不能按 run-root、arm 或 deployment/config hash 分片产生多个同账本 owner。模型部署/domain 作为租约中的身份绑定，不能使同账本的不同声明域避开互斥。sidecar 不随 ledger 原子 replace 替换或删除。

租约以 `LOCK_EX|LOCK_NB` 在预算内容加载、httpx client 或 SDK 构造前取得。第二进程立即拒绝，未读取/创建另一预算、未 reserve、未创建参与 client/SDK 或派发。PID、实际开着的 lease、canonical ledger/domain 和精确预算对象必须绑定；同一 owner 不接受第二个独立缓存的 RunBudget 对象。新进程显式重新取得租约后读原持久账本，保留原 limits、history、已知/charged/unknown，不能补造旧 unknown 的 usage、退款或重试。

生命周期覆盖实际 native evidence/snapshot、显式 SDK/client close、最后账本完成和原入口结果关闭。P5 的 evidence-before-close 保持，异常和初始化失败也按明确顺序清理；client 仍打开或请求仍活动时不能无声释放 owner。close、对象复用、lease/domain/PID 变化都可检测地拒绝。

fork 的继承 descriptor 仍指向父进程原 open-file description：child 不能使用父 owner、不能对继承 lock 做 `LOCK_UN` 释放父锁，不能在拿旧缓存的情况下构造/派发。PID 检查必须先于可能继承为 locked 的线程 mutex，避免 child 永久等父线程；必要的 fork cleanup 只关闭 child descriptor并拒绝使用。支持范围是合作本地 Linux 进程，不保证非合作写、任意外部回滚、恶意 monkeypatch、网络文件系统或分布式服务。

### 完整请求互斥与持久计费

所有绑定该预算的 VLLMClient 自动参与同一 owner；额外显式 owner 参数若存在，必须与预算同一个对象，不能旁路。在 client 构造前、每次请求前核对真实配置/实际 base URL/请求路径与 model、owner/domain/PID/精确预算对象。Host、embedding、native callbacks、M ordinary/writer、共同 P5 比较和未来使用同一 transport 的 summary 路由均遵循实际绑定；未实现的 summary 路由不得冒充执行样本。

一个进程共享的 primitive request mutex 从预算 reserve 之前持续至 dispatch、原 trace/receipt、finish 和 finally。同线程重入在等待 mutex 前拒绝；不是递归锁或自动队列重试。native 外层锁继续是不同锁，避免嵌套同一锁。锁顺序不得引入预算锁与请求锁的反向依赖。

opt-in reserve 必须在真正派发前把原账本 reservation flush/fsync 并完成原子 replace及目录 fsync；unknown 保留 charged reservation，断进程之后由真实持久字节决定。新 profile 下缺失、坏格式/不兼容/机械可察觉的 stale ledger、错误预算/来源及重复或未授权 completion 不能继续改变账本/派发。reserve/finish/持久化/transport 失败不自动重试、不退款、不补0；原非负实际 known usage 和 unknown 的计费规则保留，错误/部分落盘的实际字节与结果如实存档，不把落盘失败改称事务成功。旧 `artifact_io.write_json`、RunLimits 和 ledger JSON schema保持；新持久化仅限 opt-in 分支，原历史附加数据不删除。

## 精确可改与只读范围

只改5个既有运行文件：`harness/contextual_artifacts.py` 的 RunBudget/直接关联 factory（Trace 等其余职责不改）、`providers/contextual_vllm.py` 及实际 D0/P5/`v13_1_baseline_micro` 入口。允许新增一个 stdlib `harness/http_ownership.py` 和两份工程测试。helper 放 harness 叶层，遵守原 package DAG；不为绕过边界让 harness 导入 providers，不改变 boundary 规则。

共同 P5 比较和 Mem0/SimpleMem 原 callback 只读；它们已用传入的同一预算/客户端，要求用真实调用路径证明传递，若发现确需额外运行路径变更，先把精确路径和理由交 Root，再继续独立工作。其他既有 runners 默认合同保持，本范围不声称给未接入入口补齐所有 future actual cohort 能力。

机器范围列出5个 editable、1个新 helper、2个新测试、32个只读运行依赖及3个只读工程测试。全部213/391/316仅可完整 hash；配置、实际研究结果及原模型账本内容禁止读。允许人工读的 fixed primary 方法均在机器范围逐path/hash列出，仅作为参考，不执行/升级其代码。自动导入已有 pinned SDK 与必要 local tokenizer 是有限合成机制进口，不能据此人工展开未列出依赖内容。新合成 ledger/config/fixture/trace 只在新树 ignored artifacts/pytest basetemp 内。

所有真实命令使用新树内的 recorder，保存原 input/stdout/stderr/rc、driver 版本、执行源码 SHA 和主/隔离运行/测试/完整配置前后 maps，包含原非零，不在外部目录 bootstrap。机制控制先装 socket-denial，禁止实际网络派发；MockTransport、子进程/fork/故障和所有合成账本明确区分真实样本。不读真实实验输入/错误值，不按 gold 或案例修正。

## 有限验收目标

- 实际两个及多个参与 client/线程的 barrier/事件控制：generation+embedding交错且最大 in-flight1；同预算已知/unknown/holdback/count和原请求/响应一致。证明所有请求最终计费，不用仅启动线程或测锁存在代替。
- 两进程同 canonical ledger lease 竞争立即拒绝；不同 root/arm/domain、路径 alias仍不能绕过同账本。拒绝发生在 budget load/client/SDK构造/派发前，保留各实际子进程日志/rc/时点。不要只靠sleep猜进程存活。
- close/同线程重入/fork/PID/不同 budget/错误domain/真实client配置和model/冻结漂移/stale或缺失账本在 reserve/派发前拒绝。未知例外原传播。元数据与实际HTTP trace不混为一条假成功。
- 保留503/timeout/未知usage/reserve写失败/finish写失败/真正子进程 cut 的原字节；同原本地账本新owner重开，无额外调用/丢失 reservation。合成历史 unknown1/limits/history完整保留；这不是读真实连续账本。
- 真正 D0 prepare/_execute_step、P5 prepare/step/start/resume和baseline micro入口（合成配置、真实函数、受控 Mock）闭包：租约早于加载及构造，evidence早于SDK关闭，client关闭早于lease释放。缺失/竞争/漂移不派发；不通过只调用私有 helper 代替入口检查。
- 实际 `_ChatCompletions`/`_Embeddings` native callback 与 Host/M bridge共享 owner；原 native 外锁独立、参数/wire 不改。全部正常/错误/final/writer 的 transport 原件保存。Mock native callback不当完整native SDK/model微型验收。
- absent/explicit legacy × native/json_action × shared bridge/recipe 至少8组完整原 request/schema/catalog/grammar/ToolMessage/response/预算字节比较，排除项只允许非决定 wall/cpu 时间，明确对照所用 base 文件身份。Source当前A/B/C默认和opt-in有限受影响原检查保持。
- 新有限测试、只读受影响测试、允许5+1运行文件的mypy、5+1+2文件ruff、package/tools原双boundary；不跑会展开真实config/fixture/ledger的旧分支，不以mock数量作质量结论。

Source 最后只提交精确允许源码/新测试的一个本地 commit，不push；交完整 HANDOFF/manifest/file-index/source-checks/失败和最终字节验证/provenance，READY/HOLD。终端自引用排除与最后命令回执如实说明，不能改写早期通过为最终字节执行。Root 独立原件审计、diff/必要工程检查与另行发布接受前不接入主运行树。新真实 cohort 还需新冻结、GitHub pre-first-HTTP核对和 Root逐轨迹审查；原R7不重跑。完整plan ACTIVE、D4 NOT_ADMITTED、Product NO_GO。
