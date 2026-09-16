# V0221 HTTP-only：通路成功，首个完整动作未保真

日期：2026-09-11。终态：`LIVE_COMPAT_NOT_MET / W3_NOT_TRIGGERED / MEMORY_NOT_ADMITTED`。
按 [Goal §10.2](MILA_V0221_真实生成兼容验证与动作执行复验_GOAL_20260911.md) 完成本次有界检查和报告，
**不表示真实兼容门或动作执行门通过**。实验臂为 `SIMULATION / INTENT_ORACLE`。
[机器可复核结果](MILA_V0221_HTTP_ONLY_RESULTS_20260911.json) 保留门、完整未运行位置和三账。

## 1. 核心结果

vLLM HTTP 查询、tokenize、真实推理均工作。首个 W2 full 请求返回 HTTP 200、正常结束、
严格 JSON，并通过原完整公共 Schema；但两个字段没有忠实复制已经明确给定的动作值：

| 字段 | 已授权预期 | 原始模型输出 |
| --- | --- | --- |
| `recipient` | `hefeng@agency.com` | `f` |
| `summary` | 约定的完整商业摘要，原文保存在冻结请求中 | `S` |

动作仍是 `put_record(manager_report)`、`expected_version=0`，其余字段与预期一致。
这说明合法 JSON / Schema 不足以证明意图保真；不能归因为 GPU 不可用，也不能据此断言
vLLM、模型所有任务或 Memory 都失败。没有推断根本原因，尚未进行提示或服务端原因的对照实验。

请求 `w2-01-84ee1e179ab04480bf9413d770286dd1`，响应 ID 为对应的 `chatcmpl-...`。
输入 27,779、输出 85、总计 **27,864 raw tokens**，`finish_reason=stop`，不是达到输出上限。
HTTP 原始 usage 先落账，完整 Schema 校验后再判意图失败；没有改值、补写、去重或重试。
W2 无业务 dispatcher，未创建 live World、未保存 Note；离线参考副本的写入不计作真实模型效果。

## 2. 授权、HTTP-only 与预检修订

用户先明确授权路径 B 的 W2 / 条件 W3，后要求仅使用 vLLM、不要直接调用 GPU。
本次执行遵守 [HTTP-only 补充](../../docs/V0221_HTTP_ONLY_EXECUTION_V1.md)：
直接设备、驱动和容器调用 **0**；未重启或修改共享服务。旧设备诊断记录保留，但不再用其阻断 HTTP。
旧两份账本及唯一未知请求精确承接，没有伪造 SETTLED 或释放旧预约。

首个准备目录 `20260911-http-r1` 在本地准入校验停止：World 序列化引起顶层 `anyOf`
分支换序，旧验证器要求字面顺序一致。该次仅模型/版本 GET 成功，**生成 0、tokenize 0**，
不存在 live launch 或账本请求事件。其代码、失败和永久停止状态全部保留。

在任何真实生成前，建立本地修订 `20260911-http-r1-v2`：只按顶层分支的精确多重集合
匹配历史 CPU 覆盖，所有嵌套约束、值与分支重复次数必须相同。**实际 canonical/wire 请求不换序、不修改**。
不是扩展 Schema 编译器或再分配一个真实候选。准备器要求前版零事件、零生成、零 tokenize、
无 live launch，才能接受这一特定本地修正；不能用该入口绕过真实失败。
96 份实际参考请求离线集成核对通过且输入未被修改，7 项新增负控覆盖重复/缺失分支、
嵌套 enum 换序、移除 uniqueItems / required 和根描述变动。

## 3. 门与未运行矩阵

| 门 / 阶段 | 实际结果 |
| --- | --- |
| G_AUTH | PASS：路径 B、精确历史承接、W2/条件 W3、唯一批与期限绑定 |
| 离线完整轨迹 | 16 W2 请求 + 24 W3 参考链（80 轮），共 96 份完整请求 |
| G_PREFLIGHT | PASS：全部 96 份请求和参考输出，192 次 HTTP tokenize 全为 200 |
| 容量 | 最大输入 56,159 + 输出预留 4,096 ≤ 65,536；最大参考输出 838 |
| 当前 HTTP 身份 | Qwen3.6-35B-A3B-FP8、context 65536、vLLM 0.27.1，前后匹配 |
| W2 full | 计划 8，尝试 1，通过 0，剩余 7 未运行 |
| W2 finish | 计划 8，尝试 0，全部未运行 |
| G_LIVE_COMPAT | NOT_MET：首个请求 `LEGAL_JSON_INTENT_FIDELITY_FAILURE` |
| W3 / G_KNOWN_INTENT_V0221 | NOT_TRIGGERED：24 条链全部未运行 |
| V3–V5 / 正常业务 / Memory | 未触发 / 未证明 / 不准入 |

冻结四根原顺序 `[1,3,31,56]`、25 个完整合法对象、完整来源、8 对 full/finish 合同。
W2 完整对象选择依次为 manager_report、manager_report、placement_plan、triage，事前确定。
只复用历史安装代码 CPU 全矩阵；**没有重新证明当前容器、镜像、进程或全部启动参数指纹**。
HTTP 身份与一次真实生成的证据边界不应被扩大。

模型并发 1；W2≤16 / 1800 秒，W3≤96 / 7200 秒，链≤300 秒，HTTP≤60 秒，
输出≤4096，累计 raw cap=null，Judge=0。已知成本虽然全结算，批级永久停止仍禁止继续。
`usage_state.new_generation_allowed=true` 只表示账目已结算，**不覆盖批停止锁**。

## 4. 三账与证据

| 账目 | 已知实际 raw | 未知 / 预约 |
| --- | ---: | --- |
| 历史两批 | 2,221（2 个已结算请求） | 1 个未知，28,284 raw 预约；实际总额仍 null |
| 本次 HTTP 候选 | 27,864（1 个请求） | 新未知 0、未结预约 0 |
| Agent 自身工作 | Goal 计数快照 187,952 tokens，13:29:14 UTC | 非最终计数、非 vLLM raw、非实际账单 |

跨上述模型账已知实际为 30,085 raw，但跨批实际总额仍未知，不能把 28,284 预约相加当实际。
192 次预检 tokenize 与 1 次实际请求 tokenize 分列，不算额外模型生成。

原始目录：`/cra/memory/mx_memory/evidence/v0221/20260911-http-r1-v2/`。
执行绑定 SHA256：`117100e25e6cf47a3d9db331b728ba77fb7790b1303b57117fb22691148b75b4`。
参考索引 SHA256：`099a064e33e8a840c9b15d6f74c8acc930d8b639cdbac667a9efc8c3032f44f6`。
关键证据为 `manifest.json`、`preflight/result.json`、`batch.sqlite`、`result.json`、
`terminal-audit.json` 和 `episodes/w2-01/provider/` 内请求、响应、原始 usage、完整合同校验。
所有失败前后成本及 39 个未运行 episode ID 都保留，没有恢复旧 V2 的 23 个未运行位置。

独立只读审计复算中央/本地账、精确 wire、HTTP 输入计数与 usage、原完整 Schema、
字段差异、批停止和全部参考 hash。旧 24 个 World 仍为 version 0、空 records 和空 ledger。
原失败报告和冻结代码/输入验证不变。HTTP-only 工作没有读取或展示 HF 凭据。

## 5. 工程验收与下一最小动作

新 HTTP 接线 24 项测试 + 分支顺序 7 项测试通过，包含模拟 HTTP→原 Session→SQLite、
跨进程未知停发、授权/hash/重启/新目录负控和执行前意图拒绝。
全仓库 **1602 passed / 1 optional Host SDK skip**；边界、Ruff、Mypy（39 源文件）、构建和 diff 检查通过。
这些是工程回归，不替代 W2 16/16 或 W3 24/24。

下一最小动作是对已冻结的完整模型可见请求做零生成分析，检查为何显式授权值未被保真，
提出可预先冻结的提示/意图呈现修订与负控。任何修订后的真实请求都是第二候选，
必须新版本和新授权；不得降低 Schema/业务验收、将输出改成预期值或自行重试。
不开发 State，不改 Product/A0，不开保护池，不恢复 Memory 机制研究。
