# V0221 有界检查：SERVICE_NOT_READY，未启动真实生成

日期：2026-09-11。批：`20260911-r1`。

结论：按照 [Goal](MILA_V0221_真实生成兼容验证与动作执行复验_GOAL_20260911.md) §10.2
的有界未通过路径收口。停止在服务准入层；不是模型生成失败，不是完整 W1 接线完成，
也不是 W2/W3 或 Memory 门通过。

用户已明确回复“授权”，覆盖保留旧未知账的路径 B、W2 及条件 W3。
随后用户要求“不要乱调用gpu”：只读诊断已结束，后续没有再执行 GPU/NVML/CUDA 查询，
也不启动推理；任何未来 GPU 操作先单独征求用户同意。本报告不授权后续 GPU 操作。

## 实际执行与证据强度

| 层次 | 实际结果 | 不能外推成什么 |
| --- | --- | --- |
| 授权来源与历史承接范围 | 用户回复及提问原文封存；两份旧账/hash、精确未知请求、唯一新批、阶段/期限已核对 | 不是旧用量结算，也不是完整跨进程派发策略已接入 |
| 后端身份 | 容器/镜像/进程起始标识、库版本和源码 hash 与 wire 修复基线一致 | 不等于 GPU 可服务 |
| 选定启动参数 | 模型、65536 上下文、TP=2 等允许列表参数一致 | 未声称核验全部运行时配置或生成成功 |
| HTTP | `/v1/models` 模型/上下文匹配，`/health` 返回 200 | 不替代真实解码或 GPU 就绪证据 |
| GPU 只读检查 | 宿主机查询成功；容器内 NVML 初始化失败，退出码 255 | 不足以证明精确基础设施根因 |
| 后续有界驱动查询 | 容器新诊断进程 `cuInit(0)` 返回 100 / `CUDA_ERROR_NO_DEVICE` | 不证明已运行引擎一定不能执行 kernel，也不构成生成失败 |
| 完整请求容量/真实生成/业务执行 | 未进行 | 不记 0 分或失败样本冒充已测 |

设备节点存在，但新诊断进程无法建立可用设备枚举证据。共享服务没有重启、升级、
配置修改或 GPU 权限调整。共进行宿主机/容器 NVML 查询各一次及一次有界 CUDA 驱动查询；
无模型生成、无 CUDA context 创建或推理。用户新限制之后不再执行此类查询。

## 阶段门与未运行矩阵

- W0：收到并记录路径 B 用户授权；授权范围读取器实际校验了旧账、hash、未知清单和期限。
  授权不是 Agent 自签；凭据是对真实会话的本地记录，不伪称数字签名。
- W1：早期服务就绪检查不满足，`G_PREFLIGHT=NOT_MET_SERVICE_READINESS`，持久化 `stop.json`。
  完整批协调器、Authorized WireProvider 接线、跨进程停发集成和完整容量门**尚未实现/准入**。
  既有 wire 修复 8/8 CPU、25 完整记录等证据只读保留，不重算为本批 W1 已完成。
- W2：16 个固定位置全部 `NOT_TRIGGERED`，尝试 0，通过数 null。
  已按既定机械规则封存四个 full 意图：manager_report、manager_report、placement_plan、triage；
  仅完成完整 Schema 离线校验，未构造/计数全部实际请求，未做业务派发校准。
- W3：24 条链全部 `NOT_TRIGGERED`，未创建新 World。沿用旧根/链型/冷次序，
  旧 spec、意图和完整动作 hash 已记录，未补跑旧 23 条。
- W4：记录具体停止层、全部未运行位置、费用/未知、日志、实现缺口与下一步边界。

原四根、全部合法目标、双合同修复及完整业务校验不变。旧 V2 的 24 个 World 再次只读核验：
version=0、空 records、空业务 ledger；旧结论仍为 1 次尝试、0 条完成、23 条未运行。

## 三账与回归

| 账目 | 数值 |
| --- | --- |
| 历史已知 | 2 次已结算请求，2,221 raw tokens |
| 历史未知 | 1 次请求，28,284 raw 预约保留；历史实际总 raw=null |
| 本批模型 | 0 请求、0 actual raw、新未知 0；tokenize=0、Judge=0 |
| 代理自身工作 | 单独由线程 Goal 用量回执报告，不并入实验 raw |

新增 26 项授权范围离线负控通过：未授权/授权漂移、期限、范围、其他批/目录、假回执、
历史清单变化、旧边界违规、来源/代码 hash 等。这不是跨进程协调器的完整测试矩阵；
重启/重复启动、新批未知横跨 episode 停发以及真实 W2→W3 派发尚未集成验证。
全仓库 **1571 passed / 1 optional Host SDK skip（50.62 秒）**；边界、Ruff、Mypy
（39 源文件）、sdist/wheel 构建和 diff 检查通过。早期 Ruff 行长问题在执行封存前修正。

## 冻结制品

外部根：`/cra/memory/mx_memory/evidence/v0221/20260911-r1/`。

| 制品 | SHA256 |
| --- | --- |
| authorization.json | baf04e29453cec6a48d2f958d87eedbf53963eaa98d9458719c2d0b6fb44e50c |
| manifest.json | 92ccbb5e711412ce2d666d64fa568403f7be84e5c266780776bbaafe5552bf1e |
| result.json | ca1d901a8f74c8fa18363a3f4f36608ebe9b249aed2645331ef2f4f4ce70a7b3 |
| stop.json | 29ba82f92a8c8ad9891166534e66224c4140fba3089f4d5e01528108b97b1511 |
| service-diagnostic-v1/result.json | c0fc26821fad27aaf3e53f1e4a6a515105a8591ac0568b520cc6679558c5d5d0 |
| w4-audit-v1/result.json | ec994bd092b4e8e8db301c7f205e7b3f4070c2189ff1c860f0c573ee1fe86a91 |
| w4-audit-v1/unrun-matrix.json | 65865a48416b188d34730a1ecc2cfa0a6934191d0cd896dce4f1f9968f9cd4b7 |

原 Goal 全文/hash 保存在 `goal-frozen.json`；当前 Goal 的执行状态更新不覆盖原授权合同。
原始响应、GPU 查询输出和驱动返回码留在外部目录，Git 不收录全量运行原文或凭据。

## 下一步与终态

`SERVICE_NOT_READY_BOUNDED_CHECK_COMPLETE / LIVE_NOT_TESTED / MEMORY_NOT_ADMITTED`。
原目标的通过路径未达到；本次仅按明确允许的有界未通过分支交付。

当前停止批不得重启或扩大。若用户以后决定继续，先单独明确允许的 GPU 操作范围，
由服务维护方确认基础设施可用，再冻结新版本/新授权，并补齐上述 W1 接线及容量缺口。
不能把旧授权、HTTP 200、CPU PASS 或本报告当作继续调用 GPU/模型的许可。
没有扩任务、开发 State、改 Product/A0/Schema、打开 candidate 57 或保护池。
